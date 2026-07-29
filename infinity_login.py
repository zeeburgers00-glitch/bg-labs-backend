import httpx
import re

session = httpx.Client(follow_redirects=True)

# Get login page
resp = session.get('https://dash.infinityfree.com/login')

# Find the login form
form_match = re.search(r'<form[^>]*action="([^"]*)"[^>]*>(.*?)</form>', resp.text, re.DOTALL)
if form_match:
    action = form_match.group(1)
    form_html = form_match.group(2)
    print(f'Form action: {action}')
    
    # Find ALL input fields
    inputs = re.findall(r'<input[^>]*>', form_html)
    for inp in inputs:
        name = re.search(r'name="([^"]*)"', inp)
        itype = re.search(r'type="([^"]*)"', inp)
        value = re.search(r'value="([^"]*)"', inp)
        if name:
            print(f'  Input: name={name.group(1)}, type={itype.group(1) if itype else "text"}, value={value.group(1)[:20] if value else "none"}')

# Also check for any captcha
if 'captcha' in resp.text.lower() or 'recaptcha' in resp.text.lower():
    print('CAPTCHA detected!')

# Check page content for hints
if 'register' in resp.text.lower():
    print('Page mentions register')
if 'forgot' in resp.text.lower():
    print('Page mentions forgot password')
