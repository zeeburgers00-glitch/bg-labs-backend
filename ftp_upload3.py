import ftplib

FTP_HOST = 'ftpupload.net'
FTP_USER = 'if0_42355979'
FTP_PASS = 'pKhiFNTRjkV9R'

# Upload the FULL app
LOCAL_FILE = r'C:\Users\HP\Desktop\bg-labs-backend\bglabs_complete.html'

ftp = ftplib.FTP(FTP_HOST, timeout=30)
ftp.login(FTP_USER, FTP_PASS)
print("Connected!")

ftp.cwd('htdocs')

# Upload full app as index.html
with open(LOCAL_FILE, 'rb') as f:
    ftp.storbinary('STOR index.html', f)
print(f"Uploaded bglabs_complete.html as index.html ({268}KB)")

# Verify
files = []
ftp.retrlines('LIST', files.append)
for f in files:
    print(f"  {f}")

ftp.quit()
print("\nDONE! Full app live at: http://bglabs.wuaze.com")
