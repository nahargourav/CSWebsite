# CHAMPALAL & SONS

**A legacy of craft and care — serving customers since 1930**

Champalal & Sons is a family-run clothing and apparel company carrying four generations of craftsmanship. We focus on high-quality fabrics, timeless design, and an exceptional customer experience. This repository contains the codebase for our web storefront and order management system — built to provide a fast, secure checkout experience and smooth admin workflows.

---

## Project purpose

This project powers the Champalal & Sons online presence: product catalog, shopping cart, checkout (Razorpay integration), order tracking, and basic account management. It is intended for use by our development team and partners to run local development, testing, and production deployments.

---

## Features

* Product listing and detail pages
* Cart and checkout with Razorpay (test mode support)
* User registration and login (OAuth support via Google)
* Order recording and signature verification
* Simple admin access for order and product management

---

## Quick start (development)

> Tested with Python 3.10+. Use a virtual environment to avoid global package conflicts.

### 1. Clone the repository

```bash
git clone https://github.com/nahargourav/CSWebsite.git
cd your-repo
```

### 2. Create and activate a virtual environment

**macOS / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows (PowerShell):**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install Python dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure environment variables

Copy the `.env.template` (or the sample below) to `.env` at the project root and fill in the real values for local testing.

**`.env` template**

```env
# Payment gateway (Razorpay test credentials)
RAZORPAY_KEY_ID=rzp_test_XXXXXXXXXXXXXXXX
RAZORPAY_KEY_SECRET=rzp_test_secret_here

# Flask / Django style secret used for sessions and signing
SECRET_KEY=some_random_secret_value

GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret

# Optional: database URL (if your app uses a DB)
# e.g. SQLITE: sqlite:///data.db or POSTGRES: postgresql://user:pass@host/dbname
DATABASE_URL=sqlite:///data.db

# App settings
FLASK_ENV=development
PORT=5000
```

**Important:** Never commit real secrets or private keys to source control. Add `.env` to `.gitignore` (it should already be ignored).

### 5. Run the app (development)

```bash
python run.py
```

*on Windows PowerShell use `set` or `$env:` to set env vars accordingly.*

### 6. Open in your browser

Navigate to `http://localhost:5000` (or the port configured in `.env`).

---

## Razorpay test flow (manual)

1. Login or register as a customer.
2. Add product(s) to the cart.
3. Click **Checkout → Pay Now**.
4. Complete the test payment in Razorpay’s test UI (use test card credentials provided by Razorpay).
5. After payment completes, the server verifies the payment signature and stores `payment_id`, `payment_signature`, and `payment_status` on the respective order record.

---

## Environment & deployment notes

* For production, use real Razorpay keys (not test keys) and enable HTTPS.
* Use a proper production WSGI server (Gunicorn / uWSGI) behind a reverse proxy (Nginx) for better performance and security.
* Store secrets securely (Vault, environment variables in your host/PAAS, GitHub Secrets for CI deployments).
* If you use a managed database, set `DATABASE_URL` to that connection string and run any required migrations before starting the app.

**Example (Gunicorn)**

```bash
gunicorn -w 4 -b 0.0.0.0:8000 run:app
```

---

## Testing & debugging

* Check logs printed by `run.py` for runtime errors.
* Common issues:

  * `ModuleNotFoundError`: dependencies not installed — run `pip install -r requirements.txt`.
  * `ENV VAR missing`: ensure `.env` is present and loaded (you may need python-dotenv or similar).
  * port already in use: change `PORT` in `.env`.

---


## Security

* Rotate API keys and secrets regularly.
* Do not log sensitive data (card numbers, full signatures, secrets).
* Restrict access to admin routes and protect APIs with appropriate authentication and authorization.

---

## Contact

For questions about this repository or the product, contact the development team at `gouravnahar3008@gmail.com`.

---