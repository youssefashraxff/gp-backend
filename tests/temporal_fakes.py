"""Helpers that build real Temporal describe() protobufs, without a Temporal server."""

from types import SimpleNamespace
from typing import cast

from temporalio.api.common.v1 import ActivityType, Payloads
from temporalio.api.workflow.v1 import PendingActivityInfo
from temporalio.api.workflowservice.v1 import DescribeWorkflowExecutionResponse
from temporalio.client import WorkflowExecutionDescription
from temporalio.converter import DataConverter


async def pending_activity(name: str, heartbeat: dict | None = None) -> PendingActivityInfo:
    """A pending activity as Temporal reports it, with the heartbeat encoded like a worker would."""
    activity = PendingActivityInfo(activity_type=ActivityType(name=name))
    if heartbeat is not None:
        payloads = await DataConverter.default.encode([heartbeat])
        activity.heartbeat_details.CopyFrom(Payloads(payloads=payloads))
    return activity


def description(*activities: PendingActivityInfo) -> WorkflowExecutionDescription:
    """Wrap the raw response the same way the client does; only raw_description is read."""
    raw = DescribeWorkflowExecutionResponse(pending_activities=list(activities))
    return cast(WorkflowExecutionDescription, SimpleNamespace(raw_description=raw))
