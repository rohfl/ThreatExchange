# Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved

import bottle
import boto3
import base64
import requests
import datetime

from enum import Enum
from dataclasses import dataclass, asdict
from mypy_boto3_dynamodb.service_resource import Table
from botocore.exceptions import ClientError
import typing as t

from hmalib.lambdas.api.middleware import jsoninator, JSONifiable, DictParseable
from hmalib.common.content_models import ContentObject
from hmalib.common.logging import get_logger

logger = get_logger(__name__)
s3_client = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")


def create_presigned_put_url(bucket_name, object_name, file_type, expiration=3600):
    """
    Generate a presigned URL to share an S3 object
    """

    s3_client = boto3.client("s3")
    try:
        response = s3_client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": bucket_name,
                "Key": object_name,
                "ContentType": file_type,
            },
            ExpiresIn=expiration,
        )
    except ClientError as e:
        logger.error(e)
        return None

    return response


@dataclass
class InitUploadResponse(JSONifiable):
    content_id: str
    file_type: str
    presigned_url: str

    def to_json(self) -> t.Dict:
        return asdict(self)


@dataclass
class InitUploadRequestBody(DictParseable):
    content_id: str
    file_type: str

    @classmethod
    def from_dict(cls, d):
        return cls(d["content_id"], d["file_type"])


class SubmissionType(Enum):
    POST_URL_UPLOAD = "Upload"
    DIRECT_UPLOAD = "Direct Upload (~faster but only works for images < 3.5MB)"
    FROM_URL = "From URL"


@dataclass
class SubmitContentRequestBody(DictParseable):
    submission_type: str  # Enum SubmissionType names
    content_id: str
    content_type: str  # Only photo supported
    content_bytes_url_or_file_type: t.Union[str, bytes]
    additional_fields: t.Optional[t.List]

    @classmethod
    def from_dict(cls, d):
        # ToDo Cleaner error handling
        return cls(
            d["submission_type"],
            d["content_id"],
            d["content_type"],
            d["content_bytes_url_or_file_type"],
            d["additional_fields"],
        )


@dataclass
class SubmitContentResponse(JSONifiable):
    content_id: str
    submit_successful: bool

    def to_json(self) -> t.Dict:
        return asdict(self)


@dataclass
class SubmitContentError(JSONifiable):
    """
    Warning: by default this will still return 200
    you need to update bottle.response.status
    if you want a specific return code.
    ToDo update middleware.py to handle this.
    """

    content_id: str
    message: str

    def to_json(self) -> t.Dict:
        return asdict(self)


def record_content_submission(
    dynamodb_table: Table, image_folder_key: str, request: SubmitContentRequestBody
):
    # TODO add a confirm overwrite path for this
    submit_time = datetime.datetime.now()
    ContentObject(
        content_id=f"{image_folder_key}{request.content_id}",
        content_type=request.content_type or "PHOTO",
        content_ref=f"{image_folder_key}{request.content_id}",  # raw bytes + tmp urls are a bad idea atm, assume s3 object for now
        content_ref_type=request.submission_type,
        additional_fields=set(request.additional_fields)
        if request.additional_fields
        else set(),
        submission_times=[submit_time],  # Note: custom write_to_table impl appends.
        created_at=submit_time,
        updated_at=submit_time,
    ).write_to_table(dynamodb_table)


def get_submit_api(
    dynamodb_table: Table, image_bucket_key: str, image_folder_key: str
) -> bottle.Bottle:
    """
    A Closure that includes all dependencies that MUST be provided by the root
    API that this API plugs into. Declare dependencies here, but initialize in
    the root API alone.
    """

    # A prefix to all routes must be provided by the api_root app
    # The documentation below expects prefix to be '/submit/'
    submit_api = bottle.Bottle()

    # Set of helpers that could be split into there own submit endpoints depending on longterm design choices

    def direct_upload(
        request: SubmitContentRequestBody,
    ) -> t.Union[SubmitContentResponse, SubmitContentError]:
        """
        Direct transfer of bits to system's s3 bucket
        """
        fileName = request.content_id
        fileContents = base64.b64decode(request.content_bytes_url_or_file_type)

        # We want to record the submission before triggering and processing on
        # the content itself therefore we write to dynamo before s3
        record_content_submission(dynamodb_table, image_folder_key, request)

        # TODO a whole bunch more validation and error checking...
        s3_client.put_object(
            Body=fileContents,
            Bucket=image_bucket_key,
            Key=f"{image_folder_key}{fileName}",
        )

        return SubmitContentResponse(
            content_id=request.content_id, submit_successful=True
        )

    def post_url_upload(
        request: SubmitContentRequestBody,
    ) -> t.Union[InitUploadResponse, SubmitContentError]:
        """
        Submission of content to the system's s3 bucket by providing a post url to client
        """
        # TODO error checking on if key already exist etc.
        presigned_url = create_presigned_put_url(
            bucket_name=image_bucket_key,
            object_name=f"{image_folder_key}{request.content_id}",
            file_type=request.content_bytes_url_or_file_type,
        )

        if presigned_url:
            record_content_submission(dynamodb_table, image_folder_key, request)
            return InitUploadResponse(
                content_id=request.content_id,
                file_type=str(request.content_bytes_url_or_file_type),
                presigned_url=presigned_url,
            )

        bottle.response.status = 400
        return SubmitContentError(
            content_id=request.content_id,
            message="not yet supported",
        )

    def from_url(
        request: SubmitContentRequestBody,
    ) -> t.Union[SubmitContentResponse, SubmitContentError]:
        """
        Submission via a url to content. Current behavior copies content into the system's s3 bucket.
        """
        fileName = request.content_id
        url = request.content_bytes_url_or_file_type
        response = requests.get(url)
        # TODO better checks that the URL actually worked...
        if response and response.content:
            # TODO a whole bunch more validation and error checking...

            # Again, We want to record the submission before triggering and processing on
            # the content itself therefore we write to dynamo before s3
            record_content_submission(dynamodb_table, image_folder_key, request)

            # Right now this makes a local copy in s3 but future changes to
            # pdq_hasher should allow us to avoid storing to our own s3 bucket
            # (or possibly give the api/user the option)
            s3_client.put_object(
                Body=response.content,
                Bucket=image_bucket_key,
                Key=f"{image_folder_key}{fileName}",
            )

            return SubmitContentResponse(
                content_id=request.content_id, submit_successful=True
            )
        else:
            bottle.response.status = 400
            return SubmitContentError(
                content_id=request.content_id,
                message="url submitted could not be read from",
            )

    @submit_api.post("/", apply=[jsoninator(SubmitContentRequestBody)])
    def submit(
        request: SubmitContentRequestBody,
    ) -> t.Union[SubmitContentResponse, InitUploadResponse, SubmitContentError]:
        """
        Endpoint to allow for the general submission of content to the system
        """

        assert isinstance(request, SubmitContentRequestBody)
        logger.debug(f"Content Submit Request Received {request.content_id}")

        if request.submission_type == SubmissionType.DIRECT_UPLOAD.name:
            return direct_upload(request)
        elif request.submission_type == SubmissionType.POST_URL_UPLOAD.name:
            return post_url_upload(request)
        elif request.submission_type == SubmissionType.FROM_URL.name:
            return from_url(request)
        else:
            # Other possible submission types are not supported so just echo content_id for testing
            bottle.response.status = 422
            return SubmitContentError(
                content_id=request.content_id,
                message="submission_type not yet supported",
            )

    @submit_api.post("/init-upload/", apply=[jsoninator(InitUploadRequestBody)])
    def init_upload(
        request: InitUploadRequestBody,
    ) -> t.Union[InitUploadResponse, SubmitContentError]:
        """
        Endpoint to provide requester with presigned url to upload a photo
        """

        # TODO error checking on if key already exist etc.
        presigned_url = create_presigned_put_url(
            bucket_name=image_bucket_key,
            object_name=f"{image_folder_key}{request.content_id}",
            file_type=request.file_type,
        )
        if presigned_url:
            return InitUploadResponse(
                content_id=request.content_id,
                file_type=request.file_type,
                presigned_url=presigned_url,
            )

        bottle.response.status = 400
        return SubmitContentError(
            content_id=request.content_id,
            message="not yet supported",
        )

    return submit_api
