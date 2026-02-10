from __future__ import annotations

import io
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CREDENTIALS_FILE = PROJECT_ROOT / "credentials.json"
DEFAULT_TOKEN_FILE = PROJECT_ROOT / "token.json"
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
DEFAULT_DRIVE_ROOTS = {
    "diario": "1YZ3WYpIsQtw_0vO0A6ugVTB7AZblFfbu",
    "semanal": "1rHo2aJV-EsNrn3G-8uQUP6pAs6Sgoyu3",
    "mensal": "1esY0pBwk9kvMujQCmguEh3kGBXih_RFg",
}
MAP_TYPE_ALIASES = {
    "diario": "diario",
    "diário": "diario",
    "semanal": "semanal",
    "mensal": "mensal",
}
MONTH_NAMES_PT = {
    1: "01_JANEIRO",
    2: "02_FEVEREIRO",
    3: "03_MARCO",
    4: "04_ABRIL",
    5: "05_MAIO",
    6: "06_JUNHO",
    7: "07_JULHO",
    8: "08_AGOSTO",
    9: "09_SETEMBRO",
    10: "10_OUTUBRO",
    11: "11_NOVEMBRO",
    12: "12_DEZEMBRO",
}


@dataclass(frozen=True)
class DriveUploadResult:
    file_id: str
    name: str
    web_view_link: str | None
    web_content_link: str | None
    folder_id: str | None = None


def is_drive_upload_configured(map_type: str = "diario") -> bool:
    creds_path, token_path = _resolve_auth_files()
    root_id = get_root_folder_id(map_type)
    return creds_path.exists() and token_path.exists() and bool(root_id)


def get_root_folder_id(map_type: str) -> str:
    normalized_type = normalize_map_type(map_type)
    env_name = f"GOOGLE_DRIVE_ROOT_{normalized_type.upper()}"
    env_value = os.getenv(env_name, "").strip()
    if env_value:
        return env_value
    root = DEFAULT_DRIVE_ROOTS.get(normalized_type, "").strip()
    if not root:
        raise RuntimeError(f"No root folder configured for map type: {map_type}")
    return root


def normalize_map_type(map_type: str) -> str:
    normalized = str(map_type or "").strip().lower()
    if normalized not in MAP_TYPE_ALIASES:
        raise ValueError(f"Invalid map type: {map_type}")
    return MAP_TYPE_ALIASES[normalized]


class GoogleDriveUploader:
    def __init__(
        self,
        *,
        credentials_file: str | None = None,
        token_file: str | None = None,
    ) -> None:
        creds = _load_user_credentials(
            credentials_file=credentials_file,
            token_file=token_file,
        )
        self.service = build("drive", "v3", credentials=creds, cache_discovery=False)

    def upload_map_pdf(
        self,
        *,
        map_type: str,
        target_date: date,
        filename: str,
        file_bytes: bytes,
    ) -> DriveUploadResult:
        folder_id = self.ensure_map_folder(
            map_type=map_type,
            target_date=target_date,
        )
        created = self._upsert_pdf(
            parent_id=folder_id,
            filename=filename,
            file_bytes=file_bytes,
        )
        return DriveUploadResult(
            file_id=created["id"],
            name=created.get("name", filename),
            web_view_link=created.get("webViewLink"),
            web_content_link=created.get("webContentLink"),
            folder_id=folder_id,
        )

    def ensure_map_folder(self, *, map_type: str, target_date: date) -> str:
        normalized_type = normalize_map_type(map_type)
        root_id = get_root_folder_id(normalized_type)

        year_folder = str(target_date.year)
        month_folder = MONTH_NAMES_PT[target_date.month]
        day_folder = target_date.strftime("%d")

        current_parent = root_id
        current_parent = self._ensure_folder(parent_id=current_parent, folder_name=year_folder)
        current_parent = self._ensure_folder(parent_id=current_parent, folder_name=month_folder)

        if normalized_type in {"diario", "semanal"}:
            current_parent = self._ensure_folder(parent_id=current_parent, folder_name=day_folder)

        return current_parent

    def _upsert_pdf(self, *, parent_id: str, filename: str, file_bytes: bytes) -> dict:
        matches = self._find_files(
            parent_id=parent_id,
            file_name=filename,
            mime_type="application/pdf",
        )
        canonical = matches[0] if matches else None
        duplicate_ids = [item["id"] for item in matches[1:]]

        media = MediaIoBaseUpload(
            io.BytesIO(file_bytes),
            mimetype="application/pdf",
            resumable=False,
        )

        if canonical:
            updated = (
                self.service.files()
                .update(
                    fileId=canonical["id"],
                    media_body=media,
                    fields="id,name,webViewLink,webContentLink",
                    supportsAllDrives=True,
                )
                .execute()
            )
            if duplicate_ids:
                self._delete_files(duplicate_ids)
            return updated

        metadata = {
            "name": filename,
            "parents": [parent_id],
            "mimeType": "application/pdf",
        }
        return (
            self.service.files()
            .create(
                body=metadata,
                media_body=media,
                fields="id,name,webViewLink,webContentLink",
                supportsAllDrives=True,
            )
            .execute()
        )

    def _ensure_folder(self, *, parent_id: str, folder_name: str) -> str:
        matches = self._find_files(
            parent_id=parent_id,
            file_name=folder_name,
            mime_type=FOLDER_MIME_TYPE,
        )
        if matches:
            # Keep deterministic folder selection to avoid path drift when
            # legacy duplicates exist.
            return matches[0]["id"]

        created = (
            self.service.files()
            .create(
                body={
                    "name": folder_name,
                    "mimeType": FOLDER_MIME_TYPE,
                    "parents": [parent_id],
                },
                fields="id",
                supportsAllDrives=True,
            )
            .execute()
        )
        return created["id"]

    def _find_file_id(self, *, parent_id: str, file_name: str, mime_type: str) -> str | None:
        matches = self._find_files(
            parent_id=parent_id,
            file_name=file_name,
            mime_type=mime_type,
            page_size=1,
        )
        if not matches:
            return None
        return matches[0]["id"]

    def _find_files(
        self,
        *,
        parent_id: str,
        file_name: str,
        mime_type: str,
        page_size: int = 100,
    ) -> list[dict]:
        query = (
            f"'{parent_id}' in parents and "
            f"name = '{_escape_query_value(file_name)}' and "
            f"mimeType = '{mime_type}' and trashed = false"
        )
        response = (
            self.service.files()
            .list(
                q=query,
                fields="files(id,name,createdTime,modifiedTime)",
                pageSize=page_size,
                orderBy="createdTime asc",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        return response.get("files", [])

    def _delete_files(self, file_ids: list[str]) -> None:
        for file_id in file_ids:
            try:
                (
                    self.service.files()
                    .delete(fileId=file_id, supportsAllDrives=True)
                    .execute()
                )
            except Exception:
                # Best-effort cleanup. Canonical file is already updated.
                pass


def _resolve_auth_files() -> tuple[Path, Path]:
    creds_path = Path(
        os.getenv("GOOGLE_OAUTH_CREDENTIALS_FILE", str(DEFAULT_CREDENTIALS_FILE))
    )
    token_path = Path(os.getenv("GOOGLE_OAUTH_TOKEN_FILE", str(DEFAULT_TOKEN_FILE)))
    return creds_path, token_path


def _load_user_credentials(
    *,
    credentials_file: str | None,
    token_file: str | None,
) -> Credentials:
    creds_path, token_path = _resolve_auth_files()
    if credentials_file:
        creds_path = Path(credentials_file)
    if token_file:
        token_path = Path(token_file)

    if not creds_path.exists():
        raise RuntimeError(f"OAuth credentials file not found: {creds_path}")
    if not token_path.exists():
        raise RuntimeError(f"OAuth token file not found: {token_path}")

    creds = Credentials.from_authorized_user_file(str(token_path), DRIVE_SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json(), encoding="utf-8")

    if not creds or not creds.valid:
        raise RuntimeError(
            "OAuth token is invalid and could not be refreshed. "
            f"Check token file: {token_path}"
        )
    return creds


def _escape_query_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")
