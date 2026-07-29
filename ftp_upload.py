import ftplib
import os

FTP_HOST = 'ftpupload.net'
FTP_USER = 'if0_42355979'
FTP_PASS = 'pKhiFNTRjkV9R'
LOCAL_FILE = r'C:\Users\HP\Desktop\bg-labs-backend\index.html'
REMOTE_FILE = 'index.html'

print(f"Connecting to {FTP_HOST}...")
try:
    ftp = ftplib.FTP(FTP_HOST, timeout=15)
    ftp.login(FTP_USER, FTP_PASS)
    print(f"Connected! Welcome message: {ftp.getwelcome()[:100]}")
    
    # List directories
    dirs = []
    ftp.retrlines('LIST', dirs.append)
    print(f"\nRoot directory contents:")
    for d in dirs[:15]:
        print(f"  {d}")
    
    # Check for htdocs
    try:
        ftp.cwd('htdocs')
        print(f"\nEntered htdocs folder")
        files = []
        ftp.retrlines('LIST', files.append)
        print(f"htdocs contents:")
        for f in files[:10]:
            print(f"  {f}")
    except:
        print("No htdocs folder found")
    
    # Upload index.html to root
    print(f"\nUploading {LOCAL_FILE}...")
    with open(LOCAL_FILE, 'rb') as f:
        ftp.storbinary(f'STOR {REMOTE_FILE}', f)
    print(f"Uploaded {REMOTE_FILE} successfully!")
    
    # Verify
    files = []
    ftp.retrlines('LIST', files.append)
    print(f"\nFiles after upload:")
    for f in files[:10]:
        print(f"  {f}")
    
    ftp.quit()
    print("\nDone!")
    
except Exception as e:
    print(f"Error: {e}")
