# OrderEase - Razorpay Integration

This project is a Flask-based simple order processing webapp. This README covers environment variables and how to test the Razorpay payment flow.

## Environment (.env)
Create or edit the `.env` file at the project root (a template already exists). Set the following values:

```
RAZORPAY_KEY_ID=rzp_test_XXXXXXXXXXXXXXXX
RAZORPAY_KEY_SECRET=your_test_secret
SECRET_KEY=some_random_flask_secret
```

Do not commit real secret keys to source control.

## Install

```powershell
pip install -r requirements.txt
```

## Run the app

```powershell
python run.py
```

## Test Razorpay Flow (manual)
1. Login or register as a customer.
2. Add product(s) to cart.
3. Click Checkout → Pay Now.
4. Complete the test payment in Razorpay test mode.
5. On success the server verifies the signature and stores `payment_id`, `payment_signature`, and `payment_status` on the `Orders` row.

## Unit tests (basic)

Run tests with:

```powershell
pytest -q
```

The tests mock DB and Razorpay client for the `/payment_success` endpoint.

*** End of README ***
