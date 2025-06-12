import os
import re
import json
import time
import mimetypes
from datetime import datetime
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request
import uvicorn

# === ROOM CONFIGURATION ===
ROOM_CONFIG = {
    "dslab": {
        "url": "http://192.168.69.34",
        "username": "admin",
        "password": "Fira@2024"
    },
    "ttcds": {
        "url": "http://192.168.69.34",
        "username": "admin",
        "password": "Fira@2024"
    },
    "smart_lab": {
        "url": "http://192.168.69.35",
        "username": "admin",
        "password": "Fira@2024"
    }
}

IMAGE_DIR = "images"
JSON_FILE = "access_logs.json"
GDRIVE_FOLDER_ID = "1QGBy_4JsnvfivY6yrYuo9BYSXBJg5APl"
SCOPES = ['https://www.googleapis.com/auth/drive']

app = FastAPI(title="Camera Logs with Auto Upload")

# === Google Drive Auth ===
def authenticate():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=8080)
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    return creds

def file_exists(service, file_name):
    query = f"'{GDRIVE_FOLDER_ID}' in parents and name='{file_name}' and trashed=false"
    result = service.files().list(q=query, spaces='drive', fields="files(id, name)").execute()
    files = result.get("files", [])
    return files[0]["id"] if files else None

def ensure_subfolder(service, folder_name):
    query = f"'{GDRIVE_FOLDER_ID}' in parents and name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    result = service.files().list(q=query, spaces='drive', fields="files(id, name)").execute()
    folders = result.get("files", [])
    if folders:
        return folders[0]["id"]
    folder_metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [GDRIVE_FOLDER_ID]
    }
    folder = service.files().create(body=folder_metadata, fields="id").execute()
    return folder.get("id")

def upload_file(service, file_path, file_name, parent_folder_id):
    mime_type = mimetypes.guess_type(file_path)[0]
    file_metadata = {"name": file_name, "parents": [parent_folder_id]}
    media = MediaFileUpload(file_path, mimetype=mime_type)
    file = service.files().create(body=file_metadata, media_body=media, fields="id").execute()
    return file.get("id")

def extract_logs(room_name):
    config = ROOM_CONFIG.get(room_name)
    if not config:
        raise ValueError(f"Không tìm thấy thông tin cấu hình cho phòng '{room_name}'")

    url = config['url']
    username = config['username']
    password = config['password']

    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(options=options)

    driver.get(url)
    username_input = WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "username")))
    password_input = driver.find_element(By.ID, "password")
    username_input.clear()
    username_input.send_keys(username)
    password_input.clear()
    password_input.send_keys(password)
    driver.find_element(By.CLASS_NAME, "login-btn").click()

    menu_search = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, "a[ng-click=\"home.jumpTo('home.eventSearch')\"]"))
    )
    menu_search.click()

    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CLASS_NAME, "Wdate")))
    start_input = driver.find_elements(By.CLASS_NAME, "Wdate")[0]
    end_input = driver.find_elements(By.CLASS_NAME, "Wdate")[1]

    now = datetime.now()
    start_str = now.replace(hour=0, minute=0, second=0).strftime("%Y-%m-%d %H:%M:%S")
    end_str = now.replace(hour=23, minute=59, second=59).strftime("%Y-%m-%d %H:%M:%S")

    driver.execute_script("arguments[0].removeAttribute('readonly')", start_input)
    start_input.clear()
    start_input.send_keys(start_str)
    driver.execute_script("arguments[0].removeAttribute('readonly')", end_input)
    end_input.clear()
    end_input.send_keys(end_str)

    driver.find_element(By.CLASS_NAME, "btn-save").click()

    os.makedirs(IMAGE_DIR, exist_ok=True)
    records = []
    current_page = 1

    while True:
        time.sleep(2)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
        if not rows:
            break

        for row in rows:
            cols = row.find_elements(By.TAG_NAME, "td")
            if len(cols) < 7:
                continue
            emp_id = cols[1].text.strip()
            name = cols[2].text.strip()
            card = cols[3].text.strip()
            event = cols[4].text.strip()
            ts = cols[5].text.strip()
            op = ""
            img_path = ""
            try:
                i_tags = cols[6].find_elements(By.TAG_NAME, "i")
                if i_tags:
                    ng_click = i_tags[0].get_attribute("ng-click")
                    match = re.search(r"'(http[^']+)'", ng_click)
                    if match:
                        op = match.group(1).strip()
                        safe_name = re.sub(r'[\\/*?:"<>|]', '_', name)
                        safe_time = ts.replace(':', '-').replace(' ', '_')
                        img_filename = f"{room_name}_{safe_name}_{safe_time}.jpg"
                        img_path = os.path.join(IMAGE_DIR, img_filename)

                        driver.execute_script("window.open('');")
                        driver.switch_to.window(driver.window_handles[1])
                        driver.get(op)
                        WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.TAG_NAME, "img"))
                        ).screenshot(img_path)
                        driver.close()
                        driver.switch_to.window(driver.window_handles[0])
            except:
                pass
            records.append({
                "Employee ID": emp_id,
                "Name": name,
                "Card No.": card,
                "Event Types": event,
                "Operation": op,
                "Time": ts,
                "Image": img_path
            })

        pages = driver.find_elements(By.CLASS_NAME, "ng-binding")
        found = False
        for p in pages:
            if p.text.strip() == str(current_page + 1):
                p.click()
                current_page += 1
                found = True
                break
        if not found:
            break

    driver.quit()

    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

@app.get("/logs", summary="Trích xuất log và trả về file JSON")
def download_json_file(room_name: str = Query(..., description="Tên phòng: dslab, ttcds, smart_lab")):
    try:
        extract_logs(room_name)
        creds = authenticate()
        service = build('drive', 'v3', credentials=creds)

        with open(JSON_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        for rec in data:
            img_path = rec.get("Image")
            if not img_path or not os.path.exists(img_path):
                rec["Image_Link"] = None
                continue
            file_name = os.path.basename(img_path)
            file_id = file_exists(service, file_name)
            if not file_id:
                try:
                    subfolder_id = ensure_subfolder(service, room_name)
                    file_id = upload_file(service, img_path, file_name, subfolder_id)
                except:
                    file_id = None
            rec["Image_Link"] = f"https://drive.google.com/uc?id={file_id}" if file_id else None

        with open(JSON_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        for file in os.listdir(IMAGE_DIR):
            try:
                os.remove(os.path.join(IMAGE_DIR, file))
            except Exception as e:
                print(f"⚠️ Không thể xóa file {file}: {e}")

        return JSONResponse(content=data, media_type='application/json')
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

if __name__ == "__main__":
    import sys
    uvicorn.run("app_camera:app", host="0.0.0.0", port=5005, reload=False)
