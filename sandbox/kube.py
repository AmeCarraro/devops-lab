"""The few calls to the Kubernetes API that the sandbox needs, over plain HTTPS.

Kubernetes gives every pod three files: a token that says which service account it
is, the certificate of the API server, and the name of its namespace. With them a
pod talks to the API like kubectl does, and may do only what the roles bound to
its service account allow (k8s/bootstrap/sandbox.yaml).
"""
import ssl
from pathlib import Path

import httpx2

API = "https://kubernetes.default.svc"
ACCOUNT = Path("/var/run/secrets/kubernetes.io/serviceaccount")


class Kube:
    def __init__(self, namespace: str):
        self.jobs = f"/apis/batch/v1/namespaces/{namespace}/jobs"
        self.pods = f"/api/v1/namespaces/{namespace}/pods"
        self._trust = None

    def _client(self) -> httpx2.AsyncClient:
        if self._trust is None:
            self._trust = ssl.create_default_context(cafile=str(ACCOUNT / "ca.crt"))
        # the token is read at every call: Kubernetes replaces the file before it expires
        token = (ACCOUNT / "token").read_text()
        return httpx2.AsyncClient(
            base_url=API, verify=self._trust, timeout=15, headers={"Authorization": f"Bearer {token}"}
        )

    async def create_job(self, manifest: dict) -> None:
        async with self._client() as client:
            response = await client.post(self.jobs, json=manifest)
            response.raise_for_status()

    async def job(self, name: str) -> dict | None:
        async with self._client() as client:
            response = await client.get(f"{self.jobs}/{name}")
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()

    async def pod_of(self, job: str) -> dict | None:
        """The pod of a Job: the Job controller labels it with the name of the Job."""
        async with self._client() as client:
            response = await client.get(self.pods, params={"labelSelector": f"job-name={job}"})
            response.raise_for_status()
            return next(iter(response.json()["items"]), None)

    async def log(self, pod: str) -> str:
        async with self._client() as client:
            response = await client.get(f"{self.pods}/{pod}/log", params={"tailLines": 30})
            # a pod that has not started its container yet has no log: that is not an error
            return response.text if response.status_code == 200 else ""

    async def delete_job(self, name: str) -> None:
        async with self._client() as client:
            # "Background": the Job goes now and Kubernetes removes its pod right after
            response = await client.delete(f"{self.jobs}/{name}", params={"propagationPolicy": "Background"})
            if response.status_code != 404:
                response.raise_for_status()
