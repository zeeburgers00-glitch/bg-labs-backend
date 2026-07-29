import ftplib

ftp = ftplib.FTP('ftpupload.net', timeout=30)
ftp.login('if0_42355979', 'pKhiFNTRjkV9R')
ftp.cwd('htdocs')

# Create .htaccess
with open('custom_htaccess.txt', 'w') as f:
    f.write('DirectoryIndex index.html\n')
    f.write('Options -Indexes\n')

with open('custom_htaccess.txt', 'rb') as f:
    ftp.storbinary('STOR .htaccess', f)
print('Uploaded .htaccess to htdocs!')

# Verify all files
files = []
ftp.retrlines('LIST', files.append)
for f in files:
    print(f'  {f}')

# Check file size of index.html
ftp.voidcmd('TYPE I')
size = ftp.size('index.html')
print(f'\nindex.html size: {size} bytes')

ftp.quit()
print('\nTry: http://bglabs.ct.ws')
