---
name: use-s3
description: how to use S3 storage for file operations
license: Apache 2.0
---

To use S3 in an endpoint, first use the tool `add-s3` to add the connection to your endpoint. This makes available:
- `ctx.S3_CLIENT` — the boto3 S3 client
- `ctx.S3_DATA` — the private data bucket name
- `ctx.S3_WEB` — the public web bucket name
- `ctx.S3_PUBLIC` — the public URL to access S3

The credentials are scoped to those configured buckets. Never call
`ctx.S3_CLIENT.list_buckets()`. Do not use `head_bucket`, bucket listing, or
object listing as evidence that read/write works.

## Verifying read/write access

Use a unique temporary key in `ctx.S3_DATA`, write known bytes, read and compare
the returned bytes, and always remove the key. Report success only after the
comparison succeeds:

```python
from uuid import uuid4

def verify_read_write(args, ctx=None):
    s3 = ctx.S3_CLIENT
    bucket = ctx.S3_DATA
    key = f"trustable-check/{uuid4().hex}.txt"
    expected = b"trustable-s3-ok"
    try:
        s3.put_object(Bucket=bucket, Key=key, Body=expected)
        actual = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        if actual != expected:
            raise RuntimeError("S3 read-back content does not match")
        return {"connected": True, "read_write": "OK"}
    finally:
        s3.delete_object(Bucket=bucket, Key=key)
```

## Uploading a file

```python
def upload_file(args, ctx=None):
    s3 = ctx.S3_CLIENT
    bucket = ctx.S3_DATA

    s3.put_object(Bucket=bucket, Key="path/to/file.txt", Body="file content")
    return "uploaded"
```

## Checking if a file exists

```python
def check(s3, bucket, key):
    try:
        status = s3.head_object(Bucket=bucket, Key=key)
        size = status.get('ResponseMetadata', {}).get('HTTPHeaders', {}).get('content-length', -1)
        return f"{key} size {size}"
    except:
        return f"{key} not found"
```

## Downloading a file

```python
def download(s3, bucket, key):
    response = s3.get_object(Bucket=bucket, Key=key)
    return response['Body'].read().decode()
```

## Listing objects

List all objects in a bucket, optionally filtering by a substring:

```python
def list_objects(s3, bucket, substring=""):
    out = ""
    res = s3.list_objects_v2(Bucket=bucket)
    if 'Contents' in res:
        for obj in res['Contents']:
            name = obj['Key']
            if substring in name:
                out += f"- {name}\n"
    return out or "No objects found"
```

## Deleting objects by prefix

```python
def remove_by_prefix(s3, bucket, prefix):
    out = ""
    res = s3.list_objects_v2(Bucket=bucket)
    if 'Contents' in res:
        for obj in res['Contents']:
            key = obj['Key']
            if key.startswith(prefix):
                s3.delete_object(Bucket=bucket, Key=key)
                out += f"- removed {key}\n"
    return out or "No matching objects"
```

## Using the public web bucket

Use `ctx.S3_WEB` for files that should be publicly accessible, and `ctx.S3_PUBLIC` to build the public URL:

```python
def publish_image(args, ctx=None):
    s3 = ctx.S3_CLIENT
    bucket = ctx.S3_WEB
    public_url = ctx.S3_PUBLIC

    s3.put_object(Bucket=bucket, Key="images/logo.png", Body=image_bytes)
    return f"{public_url}/images/logo.png"
```
