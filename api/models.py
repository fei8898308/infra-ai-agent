"""Alertmanager v4 input and the minimal data sent to the model."""

import hashlib
import json
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

ShortText = Annotated[str, StringConstraints(strict=True, max_length=256)]
MapKey = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=128)]
MapValue = Annotated[str, StringConstraints(strict=True, max_length=2048)]
LabelMap = Annotated[dict[MapKey, MapValue], Field(max_length=64)]
Status = Literal["firing", "resolved"]


class Alert(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Status
    labels: LabelMap
    annotations: LabelMap = Field(default_factory=dict)
    startsAt: AwareDatetime
    endsAt: AwareDatetime
    generatorURL: Annotated[str, StringConstraints(strict=True, max_length=4096)] = ""
    fingerprint: Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{16}$")]

    @model_validator(mode="after")
    def valid_alert(self):
        if not self.labels.get("alertname"):
            raise ValueError("alertname is required")
        if self.status == "resolved" and self.endsAt < self.startsAt:
            raise ValueError("Resolved end time must not precede start time")
        return self

    def normalized(self):
        # Deliberately exclude URLs and arbitrary labels/annotations. They may
        # contain secrets or instructions. Even allowed values remain untrusted.
        return {
            "status": self.status,
            "fingerprint": self.fingerprint.lower(),
            "starts_at": self.startsAt.isoformat(),
            "ends_at": self.endsAt.isoformat() if self.status == "resolved" else None,
            "labels": {
                k: v
                for k, v in self.labels.items()
                if k
                in {
                    "alertname",
                    "instance",
                    "job",
                    "severity",
                    "device",
                    "interface",
                    "ifName",
                    "site",
                }
            },
            "annotations": {
                k: v for k, v in self.annotations.items() if k in {"summary", "description"}
            },
        }


class Notification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal["4"]
    receiver: ShortText
    status: Status
    alerts: list[Alert] = Field(min_length=1, max_length=20)
    groupLabels: LabelMap = Field(default_factory=dict)
    commonLabels: LabelMap = Field(default_factory=dict)
    commonAnnotations: LabelMap = Field(default_factory=dict)
    # Added by newer Alertmanager versions without changing protocol version 4.
    # Accepted as bounded metadata, never forwarded to the model.
    routeLabels: LabelMap = Field(default_factory=dict)
    notification_reason: ShortText = ""
    externalURL: Annotated[str, StringConstraints(strict=True, max_length=4096)] = ""
    groupKey: Annotated[str, StringConstraints(strict=True, max_length=4096)]
    truncatedAlerts: int = Field(default=0, ge=0, strict=True)

    @model_validator(mode="after")
    def consistent_status(self):
        expected = "firing" if any(a.status == "firing" for a in self.alerts) else "resolved"
        if self.status != expected:
            raise ValueError("Group status does not match alert statuses")
        if self.truncatedAlerts:
            raise ValueError("Truncated notifications cannot be analyzed completely")
        return self

    def normalized(self):
        alerts = [a.normalized() for a in self.alerts]
        return sorted(alerts, key=lambda a: json.dumps(a, sort_keys=True))

    def event_id(self):
        # Include all labels in identity, but never send unknown labels to Flowise.
        # Firing endsAt is a moving expiry time, not a new incident.
        alerts = []
        for alert in self.alerts:
            data = alert.normalized()
            data["identity_labels"] = alert.labels
            alerts.append(data)
        canonical = json.dumps(
            sorted(alerts, key=lambda a: json.dumps(a, sort_keys=True)),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()
