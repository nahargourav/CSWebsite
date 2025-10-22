"""
transfer_all_tables.py

Usage:
    - pip install psycopg2-binary
    - Edit RENDER_CONN and SUPABASE_CONN below (full postgres connection URIs)
    - Run: python transfer_all_tables.py
"""

import sys
import time
from collections import defaultdict, deque

import psycopg2
import psycopg2.extras
from psycopg2 import sql

# ----------------- CONFIG -----------------
# Put your full connection URIs here.
# Example: "postgresql://postgres:password@db.xxxxx.supabase.co:5432/postgres"
RENDER_CONN = "postgresql://my_user:8SUWSufu7kwfowzU5C74vgzUmFbciJRj@dpg-d3qvu3ili9vc73cn8kk0-a.singapore-postgres.render.com/myapp_db_dcg7"
SUPABASE_CONN = "postgresql://postgres.pxiezxcknjmkgnpgugmk:XJNAcJvtdoOz5JCo@aws-1-ap-south-1.pooler.supabase.com:5432/postgres?sslmode=require"

# Schema to copy (most apps use 'public'). You can set to None to copy all non-system schemas.
SCHEMA = "public"

# Batch size for fetching and inserting rows
BATCH_SIZE = 1000
# ------------------------------------------

def get_tables(conn, schema=None):
    q = """
    SELECT table_schema, table_name
    FROM information_schema.tables
    WHERE table_type = 'BASE TABLE'
      AND table_schema NOT IN ('pg_catalog','information_schema','pg_toast')
    """
    params = ()
    if schema:
        q += " AND table_schema = %s"
        params = (schema,)
    q += " ORDER BY table_schema, table_name"
    with conn.cursor() as cur:
        cur.execute(q, params)
        return [(r[0], r[1]) for r in cur.fetchall()]

def get_foreign_key_graph(conn, schema=None):
    """
    Returns adjacency list and set of nodes (schema.table).
    Edge: referenced_table -> referencing_table (so we can topologically sort insertion order:
    referenced table must be inserted before referencing table.)
    """
    q = """
    SELECT
      pk_ns.nspname AS pk_schema, pk_cl.relname AS pk_table,
      fk_ns.nspname AS fk_schema, fk_cl.relname AS fk_table
    FROM pg_constraint c
    JOIN pg_class fk_cl ON fk_cl.oid = c.conrelid
    JOIN pg_namespace fk_ns ON fk_ns.oid = fk_cl.relnamespace
    JOIN pg_class pk_cl ON pk_cl.oid = c.confrelid
    JOIN pg_namespace pk_ns ON pk_ns.oid = pk_cl.relnamespace
    WHERE c.contype = 'f'
    """
    params = ()
    if schema:
        q += " AND pk_ns.nspname = %s AND fk_ns.nspname = %s"
        params = (schema, schema)
    with conn.cursor() as cur:
        cur.execute(q, params)
        rows = cur.fetchall()
    graph = defaultdict(set)
    nodes = set()
    for pk_schema, pk_table, fk_schema, fk_table in rows:
        pk = f"{pk_schema}.{pk_table}"
        fk = f"{fk_schema}.{fk_table}"
        nodes.add(pk); nodes.add(fk)
        # referenced -> referencing
        graph[pk].add(fk)
    return graph, nodes

def topo_sort_tables(all_tables, fk_graph):
    """
    all_tables: list of 'schema.table'
    fk_graph: referenced -> referencing edges
    We compute topological order so referenced tables precede referencing tables.
    If cycles exist, we'll return a best-effort order (Kahn will leave nodes with cycles).
    """
    nodes = set(all_tables)
    indeg = {n: 0 for n in nodes}
    # build reverse adjacency for indegree
    adj = defaultdict(set)
    for src, targets in fk_graph.items():
        for t in targets:
            if t in nodes and src in nodes:
                adj[src].add(t)
                indeg[t] += 1

    q = deque([n for n, d in indeg.items() if d == 0])
    order = []
    while q:
        n = q.popleft()
        order.append(n)
        for nb in adj.get(n, []):
            indeg[nb] -= 1
            if indeg[nb] == 0:
                q.append(nb)

    # If cycle nodes remain (indeg > 0), append them (best-effort)
    remaining = [n for n, d in indeg.items() if d > 0]
    if remaining:
        order.extend(remaining)
    return order

def fetch_primary_key_columns(conn, schema, table):
    q = """
    SELECT a.attname
    FROM pg_index i
    JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
    WHERE i.indrelid = %s::regclass AND i.indisprimary;
    """
    full = f"{schema}.{table}"
    with conn.cursor() as cur:
        cur.execute(q, (full,))
        rows = cur.fetchall()
        return [r[0] for r in rows]

def _adapt_value_for_insert(v):
    """
    Convert Python objects that psycopg2 can't adapt by default into adaptible forms.
    - dict/list -> psycopg2.extras.Json
    - bytes/memoryview -> bytes
    - other types left unchanged
    """
    if isinstance(v, dict) or isinstance(v, list):
        return psycopg2.extras.Json(v)
    # memoryview -> bytes
    if isinstance(v, memoryview):
        return bytes(v)
    return v

def stream_copy_table(source_conn, target_conn, schema, table, batch_size=BATCH_SIZE):
    src_name = f"{schema}.{table}"
    print(f"\nCopying {src_name} ...")
    cur_name = f"src_cursor_{schema}_{table}"
    try:
        with source_conn.cursor(name=cur_name, cursor_factory=psycopg2.extras.DictCursor) as src_cur:
            src_cur.itersize = batch_size
            try:
                src_cur.execute(sql.SQL("SELECT * FROM {}.{}").format(sql.Identifier(schema), sql.Identifier(table)))
            except Exception as e:
                print(f"  ERROR executing SELECT on {src_name}: {e}")
                source_conn.rollback()
                return

            # Determine column list
            if src_cur.description:
                cols = [desc.name for desc in src_cur.description]
            else:
                print(f"  WARNING: cursor.description is None for {src_name}, falling back to information_schema for columns.")
                with source_conn.cursor() as info_cur:
                    info_cur.execute("""
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = %s AND table_name = %s
                        ORDER BY ordinal_position
                    """, (schema, table))
                    rows = info_cur.fetchall()
                    if not rows:
                        print(f"  WARNING: no columns found in information_schema for {src_name}. Skipping.")
                        return
                    cols = [r[0] for r in rows]

            if not cols:
                print(f"  WARNING: zero columns for {src_name}, skipping.")
                return

            col_identifiers = [sql.Identifier(c) for c in cols]
            col_list = sql.SQL(', ').join(col_identifiers)
            insert_stmt = sql.SQL("INSERT INTO {}.{} ({}) VALUES %s ON CONFLICT DO NOTHING").format(
                sql.Identifier(schema), sql.Identifier(table), col_list
            )

            inserted = 0
            try:
                batch = src_cur.fetchmany(batch_size)
            except Exception as e:
                print(f"  ERROR fetching rows from {src_name}: {e}")
                source_conn.rollback()
                return

            while batch:
                # Normalize rows -> tuples and adapt un-adaptable types
                values = []
                for r in batch:
                    # r will normally be a dict-like from DictCursor
                    if isinstance(r, dict) or hasattr(r, "keys"):
                        tup = tuple(_adapt_value_for_insert(r.get(c)) for c in cols)
                    else:
                        # tuple-like - adapt any nested dict/list elements
                        tup = tuple(_adapt_value_for_insert(v) for v in r)
                    values.append(tup)

                # If nothing to insert in this batch, skip
                if not values:
                    try:
                        batch = src_cur.fetchmany(batch_size)
                    except Exception as e:
                        print(f"\n  ERROR fetching next batch from {src_name}: {e}")
                        source_conn.rollback()
                        break
                    continue

                # Try to insert; on failure rollback target and continue to next table
                try:
                    with target_conn.cursor() as tgt_cur:
                        psycopg2.extras.execute_values(tgt_cur,
                                                      insert_stmt.as_string(target_conn),
                                                      values,
                                                      template=None,
                                                      page_size=batch_size)
                        target_conn.commit()
                except Exception as e:
                    # print helpful debug and rollback target so it isn't left aborted
                    print(f"\n  ERROR inserting batch into {src_name}: {e}")
                    try:
                        target_conn.rollback()
                    except Exception as re:
                        print(f"  ERROR rolling back target_conn after insert failure: {re}")
                    # stop copying this table (but continue overall run)
                    return

                inserted += len(values)
                print(f"  inserted {inserted} rows into {src_name}", end="\r")

                try:
                    batch = src_cur.fetchmany(batch_size)
                except Exception as e:
                    print(f"\n  ERROR fetching next batch from {src_name}: {e}")
                    source_conn.rollback()
                    break

            print(f"\n  finished: inserted {inserted} rows into {src_name}")

    except Exception as e:
        print(f"  ERROR with streaming cursor for {src_name}: {e}")
        try:
            source_conn.rollback()
        except:
            pass
        try:
            target_conn.rollback()
        except:
            pass
        return
def update_serial_sequences(target_conn, schema, table):
    """
    Set sequence values for serial/identity columns in target to a safe value.
    If max(column) is 0 (no rows), set sequence to 1 and mark it as NOT called (so next nextval returns 1)
    We always rollback on error to clear any aborted transactions.
    """
    try:
        with target_conn.cursor() as cur:
            cur.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                AND (column_default LIKE 'nextval(%%' OR is_identity = 'YES')
            """, (schema, table))
            cols = [r[0] for r in cur.fetchall()]

            for col in cols:
                # get sequence name
                cur.execute("SELECT pg_get_serial_sequence(%s,%s)", (f"{schema}.{table}", col))
                seq_row = cur.fetchone()
                seq = seq_row[0] if seq_row else None
                if not seq:
                    continue

                # get max value in column
                cur.execute(sql.SQL("SELECT COALESCE(MAX({col}), 0) FROM {schema}.{table}").format(
                    col=sql.Identifier(col),
                    schema=sql.Identifier(schema),
                    table=sql.Identifier(table)
                ))
                maxval = cur.fetchone()[0] or 0

                # If maxval is 0 (no rows), set sequence to 1 and is_called=False so next nextval will return 1.
                if int(maxval) <= 0:
                    # setval(seq, 1, false) - future nextval returns 1
                    cur.execute("SELECT setval(%s, %s, %s)", (seq, 1, False))
                else:
                    cur.execute("SELECT setval(%s, %s, %s)", (seq, int(maxval), True))
            target_conn.commit()
    except Exception as e:
        print(f"  warning: failed to update sequences for {schema}.{table}: {e}")
        try:
            target_conn.rollback()
        except Exception:
            pass


def main():
    print("Starting transfer...")
    try:
        src_conn = psycopg2.connect(RENDER_CONN)
    except Exception as e:
        print("Failed to connect to source (Render) DB:", e)
        sys.exit(1)
    try:
        tgt_conn = psycopg2.connect(SUPABASE_CONN)
    except Exception as e:
        print("Failed to connect to target (Supabase) DB:", e)
        src_conn.close()
        sys.exit(1)

    try:
        # 1) get tables
        tables = get_tables(src_conn, schema=SCHEMA)
        if not tables:
            print("No tables found to copy.")
            return
        table_names = [f"{s}.{t}" for s, t in tables]

        # 2) build FK graph from source (we care about relationships present)
        fk_graph, fk_nodes = get_foreign_key_graph(src_conn, schema=SCHEMA)
        # Topo sort only the tables we have
        order = topo_sort_tables(table_names, fk_graph)
        print("Planned copy order (first 50 shown):")
        for i, t in enumerate(order[:50], 1):
            print(f"  {i}. {t}")

        # 3) Copy tables in order
        for fq in order:
            s, tname = fq.split(".", 1)
            stream_copy_table(src_conn, tgt_conn, s, tname, batch_size=BATCH_SIZE)
            # update sequences for this table
            try:
                update_serial_sequences(tgt_conn, s, tname)
            except Exception as e:
                # non-fatal; continue
                print(f"  warning: failed to update sequences for {fq}: {e}")

        print("\nAll done.")
    finally:
        try:
            src_conn.close()
        except:
            pass
        try:
            tgt_conn.close()
        except:
            pass

if __name__ == "__main__":
    main()
