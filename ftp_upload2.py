import ftplib

FTP_HOST = 'ftpupload.net'
FTP_USER = 'if0_42355979'
FTP_PASS = 'pKhiFNTRjkV9R'
LOCAL_FILE = r'C:\Users\HP\Desktop\bg-labs-backend\index.html'

ftp = ftplib.FTP(FTP_HOST, timeout=15)
ftp.login(FTP_USER, FTP_PASS)
print("Connected!")

ftp.cwd('htdocs')
print("In htdocs")

with open(LOCAL_FILE, 'rb') as f:
    ftp.storbinary('STOR index.html', f)
print("Uploaded index.html!")

files = []
ftp.retrlines('LIST', files.append)
for f in files:
    print(f"  {f}")

ftp.quit()
print("\nDone! Visit: http://bglabs.wuaze.com")
