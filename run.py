# run.py
import os
import sys

# Determine instance path (same behavior as Flask default)
base_dir = os.path.abspath(os.path.dirname(__file__))
instance_path = os.path.join(base_dir, 'instance')

# Default invoice dir inside the instance folder; can be overridden by env var
default_invoice_dir = os.environ.get('INVOICE_DIR') or os.path.join(instance_path, 'invoices')
# export into environment so create_app (or other modules) can read it early
os.environ.setdefault('INVOICE_DIR', default_invoice_dir)

# make sure instance and invoices directories exist *before* app import/create
try:
    os.makedirs(instance_path, exist_ok=True)
    os.makedirs(os.environ['INVOICE_DIR'], exist_ok=True)
except Exception as e:
    # print to stderr early because app logger not available yet
    print("Could not create instance/invoice dirs:", e, file=sys.stderr)

# Now import and create app
from app import create_app
app = create_app()

if __name__ == "__main__":
    # make sure app.config gets the value too (create_app might also set it)
    app.config.setdefault('INVOICE_DIR', os.environ['INVOICE_DIR'])
    app.config['COMPANY_LOGO_PATH'] = os.path.join('static', 'images', 'C&S logo.png')
    # run normally
    app.run(debug=True)
