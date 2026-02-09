from dotenv import load_dotenv
import os
import boto3
import gzip
import shutil
from pathlib import Path
from datetime import datetime
from botocore.exceptions import NoCredentialsError, ClientError
import logging 
from pathlib import Path 

load_dotenv() 

BASE_FOLDER = Path(r"C:\automatic_backup_system")

LOG_FILE = BASE_FOLDER / "backup_log.txt" 
logging.basicConfig( 
    filename=LOG_FILE, 
    level=logging.DEBUG, 
    format="%(asctime)s [%(levelname)s] %(message)s" )
 
logging.info("Backup script started")

try:
    REGION = os.getenv("REGION")
    
    DB_BUCKET =  "database-bucket-name"
    DOCS_BUCKET = "documents-bucket-name"
    PHOTOS_BUCKET= "photo-bucket-name"
    
    # Note: BASE_FOLDER points to the script folder (automatic_desktop_folder). 
    # The data folders (database, customer-data-docs, pictures) are siblings of this folder, 
    # so we use `.parent` to step up one level and access them correctly.

    DATABASE_FOLDER = BASE_FOLDER.parent / "database"
    DOCUMENTS_FOLDER = BASE_FOLDER.parent / "customer-data-docs"
    PHOTOS_FOLDER = BASE_FOLDER.parent / "pictures" 
    STATE_FILE = BASE_FOLDER / "backup_state.txt"
   
    TODAY = datetime.now().strftime("%Y-%m-%d")
    
    # Example: log the folders being used 
    logging.debug(f"Database folder: {DATABASE_FOLDER}")
    logging.debug(f"Documents folder: {DOCUMENTS_FOLDER}") 
    logging.debug(f"Photos folder: {PHOTOS_FOLDER}") 
    logging.debug(f"State file: {STATE_FILE}")
     # Place your upload logic here # 
    logging.info("Uploading files to S3...") 
    
except Exception as e: logging.exception("An error occurred during backup")

s3 = boto3.client('s3', region_name=REGION)
sns = boto3.client("sns", region_name=REGION)

TOPIC_ARN = os.getenv("TOPIC_ARN")

def notify_owner(message, subject="Daily Backup Report"):
    try:
        sns.publish( 
            TopicArn=TOPIC_ARN,
            Subject=subject,
            Message=message
        )
    except Exception as e:
        print("SNS publish failed:", str(e))
        return None

def load_state():
    if not STATE_FILE.exists():
        return {}
    state = {}
    for line in STATE_FILE.read_text().splitlines():
        try:
            name, mtime = line.split("|")
            state[name] = mtime
        except ValueError:
            continue
    return state

def save_state(state):
    lines = [f"{k}|{v}" for k, v in state.items()]
    STATE_FILE.write_text("\n".join(lines))


def compress_csv(file_path):
    gz_path = file_path.with_suffix(".csv.gz")
    with open(file_path, "rb") as f_in:
        with gzip.open(gz_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
    return gz_path

def ensure_bucket_exists(bucket):
    try: 
        s3.head_bucket(Bucket=bucket) 
    except ClientError as e:
        raise Exception(f"Bucket {bucket} not accessible: {str(e)}")

def upload_folder(folder, bucket, compress_csv_files=False):
    ensure_bucket_exists(bucket)
    state = load_state()
    updated_state = dict(state)

    for file in folder.rglob("*"):
        if not file.is_file():
            continue

        mtime = str(file.stat().st_mtime)

        # Skip unchanged files
        if file.name in state and state[file.name] == mtime:
            continue

        upload_file = file

        if compress_csv_files and file.suffix == ".csv":
            upload_file = compress_csv(file)

        key = f"{TODAY}-{upload_file.name}"
        try:
            s3.upload_file(str(upload_file), bucket, key)
            updated_state[file.name] = mtime
        except NoCredentialsError:
            raise Exception("AWS credentials not found or invalid")
        except ClientError as e:
            raise Exception(f"Failed to upload {file.name} to {bucket}: {str(e)}")
        except OSError as e:
            raise Exception(f"File access error for {file.name}: {str(e)}")   
    save_state(updated_state)

def main():
    try:

        upload_folder(DATABASE_FOLDER, DB_BUCKET, compress_csv_files=True)
        upload_folder(DOCUMENTS_FOLDER, DOCS_BUCKET)
        upload_folder(PHOTOS_FOLDER, PHOTOS_BUCKET)

        notify_owner(f"Backup completed successfully at {TODAY}")

    except Exception as e:
        
        notify_owner(f"Backup FAILED at {TODAY}\nReason: {str(e)}")
        raise

if __name__ == "__main__":
    main()