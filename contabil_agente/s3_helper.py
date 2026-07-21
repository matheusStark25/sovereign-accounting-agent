from typing import Optional

try:
    import boto3
    from botocore.exceptions import ClientError

    BOTO3_AVAILABLE = True
except ImportError:
    boto3 = None
    ClientError = Exception
    BOTO3_AVAILABLE = False


def generate_presigned_put(
    bucket_name: str, object_name: str, expires_in: int = 3600
) -> Optional[str]:
    """Gera uma URL pré-assinada para upload (PUT) em S3."""
    if not BOTO3_AVAILABLE or boto3 is None:
        raise RuntimeError(
            "boto3 não está disponível. Instale boto3 para usar integração S3."
        )
    try:
        s3_client = boto3.client("s3")
        url = s3_client.generate_presigned_url(
            "put_object",
            Params={"Bucket": bucket_name, "Key": object_name},
            ExpiresIn=expires_in,
        )
        return url
    except ClientError as e:
        raise RuntimeError(f"Erro ao gerar presigned URL para upload: {str(e)}")


def generate_presigned_get(
    bucket_name: str, object_name: str, expires_in: int = 3600
) -> Optional[str]:
    """Gera uma URL pré-assinada para download (GET) em S3."""
    if not BOTO3_AVAILABLE or boto3 is None:
        raise RuntimeError(
            "boto3 não está disponível. Instale boto3 para usar integração S3."
        )
    try:
        s3_client = boto3.client("s3")
        url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket_name, "Key": object_name},
            ExpiresIn=expires_in,
        )
        return url
    except ClientError as e:
        raise RuntimeError(f"Erro ao gerar presigned URL para download: {str(e)}")
