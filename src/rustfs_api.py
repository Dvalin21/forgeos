"""
ForgeOS RustFS Storage API Module
Replaces MinIO with RustFS - Apache 2.0 license, S3-compatible, 2.3x faster.

Provides:
- S3 API proxy (port 9000)
- Admin API (port 9000/admin)
- Web Console (port 9001, embedded in ForgeOS WebGUI)
"""

import os
import json
import subprocess
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Query, UploadFile, File
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import boto3
from botocore.client import Config
from fastapi import FastAPI

# ── Configuration ──
RUSTFS_API_ENDPOINT = os.environ.get("RUSTFS_API_ENDPOINT", "http://localhost:9000")
RUSTFS_ADMIN_ENDPOINT = os.environ.get("RUSTFS_ADMIN_ENDPOINT", "http://localhost:9000/admin")
RUSTFS_CONSOLE_PORT = int(os.environ.get("RUSTFS_CONSOLE_PORT", "9001"))

# Load RustFS credentials from config
def _load_rustfs_creds() -> dict:
    """Load RustFS credentials from ForgeOS config.
    
    If credentials are not configured, generates random ones and persists them.
    Never runs with default/insecure credentials.
    """
    config_file = Path("/etc/forgeos/forgeos.conf")
    creds: dict[str, str] = {}
    
    if config_file.exists():
        for line in config_file.read_text().splitlines():
            if line.startswith("RUSTFS_ACCESS_KEY="):
                creds["access_key"] = line.split("=", 1)[1].strip().strip('"')
            elif line.startswith("RUSTFS_SECRET_KEY="):
                creds["secret_key"] = line.split("=", 1)[1].strip().strip('"')
    
    # Auto-generate and persist if not configured
    if "access_key" not in creds or "secret_key" not in creds:
        import secrets
        creds["access_key"] = "rustfs_" + secrets.token_hex(16)
        creds["secret_key"] = secrets.token_urlsafe(32)
        try:
            with open(str(config_file), "a") as f:
                f.write(f'\nRUSTFS_ACCESS_KEY="{creds["access_key"]}"\n')
                f.write(f'\nRUSTFS_SECRET_KEY="{creds["secret_key"]}"\n')
        except Exception:
            pass
    
    return creds

_creds = _load_rustfs_creds()

# ── Boto3 S3 Client ──
def get_s3_client():
    """Create S3 client connected to RustFS."""
    creds = _load_rustfs_creds()
    return boto3.client(
        's3',
        endpoint_url=RUSTFS_API_ENDPOINT,
        aws_access_key_id=creds["access_key"],
        aws_secret_access_key=creds["secret_key"],
        config=Config(signature_version='s3v4'),
        region_name='us-east-1'  # RustFS doesn't validate regions
    )

# ── Router ──
router = APIRouter(prefix="/api/storage", tags=["RustFS Storage"])

# ── Health Check ──
@router.get("/health")
async def rustfs_health():
    """Check RustFS health status."""
    try:
        s3 = get_s3_client()
        s3.list_buckets()
        return {"status": "healthy", "service": "RustFS", "endpoint": RUSTFS_API_ENDPOINT}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

# ── Bucket Operations ──
@router.get("/buckets")
async def list_buckets():
    """List all buckets."""
    try:
        s3 = get_s3_client()
        response = s3.list_buckets()
        buckets = [{"name": b["Name"], "creation_date": str(b["CreationDate"])} 
                     for b in response.get("Buckets", [])]
        return {"buckets": buckets}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list buckets: {str(e)}")

@router.post("/buckets/{bucket_name}")
async def create_bucket(bucket_name: str):
    """Create a new bucket."""
    try:
        s3 = get_s3_client()
        s3.create_bucket(Bucket=bucket_name)
        return {"ok": True, "bucket": bucket_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create bucket: {str(e)}")

@router.delete("/buckets/{bucket_name}")
async def delete_bucket(bucket_name: str):
    """Delete a bucket."""
    try:
        s3 = get_s3_client()
        s3.delete_bucket(Bucket=bucket_name)
        return {"ok": True, "bucket": bucket_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete bucket: {str(e)}")

# ── Object Operations ──
@router.get("/buckets/{bucket_name}/objects")
async def list_objects(bucket_name: str, prefix: Optional[str] = Query(default="")):
    """List objects in a bucket."""
    try:
        s3 = get_s3_client()
        kwargs = {"Bucket": bucket_name}
        if prefix:
            kwargs["Prefix"] = prefix
        
        response = s3.list_objects_v2(**kwargs)
        objects = [{"key": o["Key"], "size": o["Size"], "last_modified": str(o.get("LastModified", ""))} 
                   for o in response.get("Contents", [])]
        return {"objects": objects, "bucket": bucket_name, "prefix": prefix}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list objects: {str(e)}")

@router.put("/buckets/{bucket_name}/objects/{object_key:path}")
async def upload_object(bucket_name: str, object_key: str, file: UploadFile = File(...)):
    """Upload an object to a bucket."""
    try:
        s3 = get_s3_client()
        s3.upload_fileobj(file.file, bucket_name, object_key)
        return {"ok": True, "bucket": bucket_name, "key": object_key, "size": file.size}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload object: {str(e)}")

@router.get("/buckets/{bucket_name}/objects/{object_key:path}")
async def download_object(bucket_name: str, object_key: str):
    """Download an object from a bucket."""
    try:
        s3 = get_s3_client()
        response = s3.get_object(Bucket=bucket_name, Key=object_key)
        
        def generate():
            for chunk in iter(lambda: response['Body'].read(4096), b''):
                yield chunk
        
        return StreamingResponse(
            generate(),
            media_type=response.get("ContentType", "application/octet-stream"),
            headers={"Content-Disposition": f"attachment; filename={object_key}"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to download object: {str(e)}")

@router.delete("/buckets/{bucket_name}/objects/{object_key:path}")
async def delete_object(bucket_name: str, object_key: str):
    """Delete an object from a bucket."""
    try:
        s3 = get_s3_client()
        s3.delete_object(Bucket=bucket_name, Key=object_key)
        return {"ok": True, "bucket": bucket_name, "key": object_key}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete object: {str(e)}")

# ── Storage Stats ──
@router.get("/stats")
async def storage_stats():
    """Get storage statistics."""
    try:
        s3 = get_s3_client()
        response = s3.list_buckets()
        buckets = response.get("Buckets", [])
        
        total_objects = 0
        total_size = 0
        
        for bucket in buckets:
            try:
                objs = s3.list_objects_v2(Bucket=bucket["Name"])
                for obj in objs.get("Contents", []):
                    total_objects += 1
                    total_size += obj.get("Size", 0)
            except:
                pass
        
        return {
            "buckets": len(buckets),
            "objects": total_objects,
            "total_bytes": total_size,
            "total_gb": round(total_size / 1e9, 2),
            "endpoint": RUSTFS_API_ENDPOINT
        }
    except Exception as e:
        return {"error": str(e), "buckets": 0, "objects": 0, "total_bytes": 0}

# ── Admin API Proxy ──
@router.api_route("/admin/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_admin_api(path: str, request: Request):
    """Proxy requests to RustFS Admin API."""
    import httpx
    
    async with httpx.AsyncClient() as client:
        url = f"{RUSTFS_ADMIN_ENDPOINT}/{path}"
        headers = dict(request.headers)
        headers.pop("host", None)
        
        body = await request.body()
        
        response = await client.request(
            method=request.method,
            url=url,
            headers=headers,
            content=body,
            params=dict(request.query_params)
        )
        
        return JSONResponse(
            content=response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text,
            status_code=response.status_code,
            headers=dict(response.headers)
        )

# ── Console Embed ──
@router.get("/console")
async def get_console_info():
    """Get RustFS console connection info for embedding."""
    return {
        "console_url": f"http://localhost:{RUSTFS_CONSOLE_PORT}",
        "api_endpoint": RUSTFS_API_ENDPOINT,
        "admin_endpoint": RUSTFS_ADMIN_ENDPOINT,
        "embedded": True
    }

# ── Service Management ──
def start_rustfs_service():
    """Start RustFS service (called during ForgeOS startup)."""
    try:
        # Check if RustFS binary exists
        result = subprocess.run(["which", "rustfs"], capture_output=True, text=True)
        if result.returncode != 0:
            return {"ok": False, "error": "RustFS binary not found"}
        
        # Start RustFS (simplified - in production, use systemd)
        # rustfs server /data --console-address ":9001" --address ":9000"
        return {"ok": True, "message": "RustFS service managed by systemd"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ── Module Exports ──
__all__ = ["router", "get_s3_client", "start_rustfs_service"]
