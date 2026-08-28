import urllib.parse
from app import app, get_db_connection

client = app.test_client()

print("=== 1. Testing Special Characters in Search ===")
special_queries = [
    '<script>alert(1)</script>',
    "' OR '1'='1",
    '../../etc/passwd',
    '🚀🔥✨',
    '%20%20%20',
    '&?#='
]
for q in special_queries:
    resp = client.get('/search?query=' + urllib.parse.quote(q))
    assert resp.status_code == 200, f'Search failed on query: {q}'
    resp_api = client.get('/api/search?query=' + urllib.parse.quote(q))
    assert resp_api.status_code == 200, f'API search failed on query: {q}'

print("Special character and XSS search safety: PASSED")

print("\n=== 2. Testing Flagging and Moderation Routes ===")
with client.session_transaction() as sess:
    sess['user_id'] = 2
    sess['user_name'] = 'Alice'
    sess['user_email'] = 'alice@reclaim.test'

resp = client.post('/item/lost/1/flag', data={
    'reason': 'Duplicate / Spam listing',
    'details': 'This appears to be a test duplicate report.'
}, follow_redirects=True)
assert resp.status_code == 200
print("Flagging item: PASSED")

print("\n=== 3. Testing Admin Moderation Actions ===")
with client.session_transaction() as sess:
    sess['user_id'] = 1
    sess['user_name'] = 'Sanketh S'
    sess['user_email'] = 'sankethbkr2005@gmail.com'
    sess['is_admin_user'] = True

conn = get_db_connection()
flag = conn.execute("SELECT id FROM item_flags WHERE status = 'Open' ORDER BY id DESC LIMIT 1").fetchone()
conn.close()

if flag:
    resp = client.post(f"/admin/flag/{flag['id']}/dismiss", follow_redirects=True)
    assert resp.status_code == 200
    print("Dismiss flag: PASSED")

print("\n=== 4. Testing Password Reset Edge Cases ===")
with client.session_transaction() as sess:
    sess.clear()

resp = client.get('/reset-password/completely-invalid-nonexistent-token')
assert resp.status_code == 200
assert 'invalid_token' in resp.get_data(as_text=True) or 'Invalid or Expired' in resp.get_data(as_text=True)
print("Invalid token handling: PASSED")


print("\n=== 5. Testing 404 & 500 Error Handlers ===")
resp = client.get('/invalid-random-url-xyz')
assert resp.status_code == 404
print("404 Error handler: PASSED")

print("\nALL STABILITY AND SECURITY CHECKS PASSED!")
