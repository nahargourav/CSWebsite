import json
import pytest
from unittest.mock import MagicMock, patch

from app import create_app


class DummyCursor:
    def __init__(self):
        self.lastrowid = 1
    def execute(self, *args, **kwargs):
        pass
    def fetchone(self):
        return None
    def close(self):
        pass


class DummyConn:
    def __init__(self):
        self.cursor_obj = DummyCursor()
    def cursor(self):
        return self.cursor_obj
    def commit(self):
        pass
    def rollback(self):
        pass
    def close(self):
        pass


@pytest.fixture
def client():
    app = create_app()
    app.config['TESTING'] = True
    app.config['PROPAGATE_EXCEPTIONS'] = True
    with app.test_client() as client:
        yield client


@patch('app.routes.get_db')
@patch('app.routes.razorpay', create=True)
def test_payment_success_verification_and_db_insert(mock_razorpay, mock_get_db, client):
    # Prepare mocks
    mock_get_db.return_value = DummyConn()
    mock_client = MagicMock()
    mock_client.utility.verify_payment_signature.return_value = True
    mock_razorpay.Client.return_value = mock_client

    # Build pending order in session via test client - simulate session by setting directly
    with client.session_transaction() as sess:
        sess['pending_order'] = {
            'cart': {'1': {'quantity': 1, 'price': 10.0}},
            'customer_id': 1,
            'total_amount': 10.0,
            'razorpay_order_id': 'order_test_1'
        }

    payload = {
        'razorpay_payment_id': 'pay_test_1',
        'razorpay_order_id': 'order_test_1',
        'razorpay_signature': 'sig_test_1'
    }

    resp = client.post('/payment_success', data=json.dumps(payload), content_type='application/json')
    if resp.status_code != 200:
        # helpful debug output when tests fail
        print('\nRESPONSE BODY:\n', resp.get_data(as_text=True))
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['status'] == 'ok'

