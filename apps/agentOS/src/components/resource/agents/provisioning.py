"""受信模板驱动的 Agent 副本创建与生命周期编排。

模板是应用装配时登记的可信 callable；运行期请求只能选择模板和幂等键，
不能提交 import 路径、Python 代码或新的能力声明。实例事实仍由 AgentPool
与 ResourcePlane 持有，租约仍由既有 LeaseCoordinator 持有。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from threading import RLock
from typing import Callable, Iterable

from components.resource.catalog.contracts import InstallationJob, InstallationStatus
from components.resource.catalog.ports import InstallationJobStore
from components.resource.scheduler.leases import LeaseCoordinator
from contracts.agents import AgentDefinition, AgentRegistrationRef

from contracts.agent_runtime import AgentNotFound, BaseAgent
from .pool import AgentPool


@dataclass(frozen=True)
class AgentTemplate:
    """A trusted construction recipe captured during application assembly."""

    template_id: str
    definition: AgentDefinition
    factory: Callable[[], BaseAgent]
    max_instances: int = 8
    dependencies: tuple[str, ...] = ()
    health_check: Callable[[BaseAgent], bool] | None = None


class AgentProvisioner:
    """Create, publish, drain and reclaim local Agent instances."""

    def __init__(
        self,
        *,
        pool: AgentPool,
        jobs: InstallationJobStore,
        coordinator: LeaseCoordinator,
        templates: Iterable[AgentTemplate] = (),
        refresh_runtime: Callable[[], object] | None = None,
    ) -> None:
        host = pool.resource_plane.runtime(pool.host_runtime_id)
        if host.owner_scope not in {None, "local"} or (host.endpoint and host.endpoint.protocol != "local"):
            raise ValueError("agent provisioning requires a shared local execution host")
        self.pool = pool
        self.jobs = jobs
        self.coordinator = coordinator
        self.refresh_runtime = refresh_runtime
        self._templates: dict[str, AgentTemplate] = {}
        self._seeds: list[BaseAgent] = []
        self._lock = RLock()
        for template in templates:
            self.register_template(template)

    @staticmethod
    def _scope(value: str) -> str:
        scope = str(value or "").strip()
        if scope != "local":
            raise ValueError("agent provisioning supports only the shared local pool")
        return scope

    def register_template(self, template: AgentTemplate) -> None:
        if not isinstance(template, AgentTemplate):
            raise TypeError("agent template must be an AgentTemplate")
        template_id = str(template.template_id).strip()
        if not template_id or any(char.isspace() for char in template_id):
            raise ValueError("agent template id must be a nonblank token")
        if not callable(template.factory):
            raise ValueError("agent template factory must be callable")
        if type(template.max_instances) is not int or template.max_instances < 1:
            raise ValueError("agent template max_instances must be positive")
        with self._lock:
            if not any(item.definition == template.definition for item in self.pool.registry.registrations()):
                raise ValueError("agent template must reuse an already published definition")
            current = self._templates.get(template_id)
            if current is not None and current != template:
                raise ValueError("agent template cannot be redefined at runtime")
            self._templates[template_id] = template

    def register_agent_template(
        self,
        template_id: str,
        *,
        seed: BaseAgent,
        factory: Callable[[], BaseAgent],
        max_instances: int = 8,
        dependencies: Iterable[str] = (),
        health_check: Callable[[BaseAgent], bool] | None = None,
    ) -> None:
        """Capture an already registered implementation as a safe template."""
        try:
            registration = self.pool.registry.get_registration(
                self.pool.registry.registration_for(seed)
            )
        except AgentNotFound as exc:
            raise ValueError("template seed must be a currently registered Agent") from exc
        self.register_template(AgentTemplate(
            template_id=str(template_id).strip(),
            definition=registration.definition,
            factory=factory,
            max_instances=max_instances,
            dependencies=tuple(str(item).strip() for item in dependencies if str(item).strip()),
            health_check=health_check,
        ))
        self._seeds.append(seed)

    def templates(self) -> list[dict]:
        with self._lock:
            result = []
            for template in self._templates.values():
                result.append({
                    "templateId": template.template_id,
                    "agentId": template.definition.agent_id,
                    "agentName": template.definition.agent_name,
                    "definitionVersion": template.definition.definition_version,
                    "capabilities": list(template.definition.capabilities),
                    "domain": template.definition.domain,
                    "maxInstances": template.max_instances,
                    "dependencies": list(template.dependencies),
                })
            return result

    def owns(self, job: InstallationJob) -> bool:
        return bool(job.job_id.startswith("agent-provision:")
                    and job.catalog_id and job.catalog_id.startswith("agent:"))

    def _job_id(self, template_id: str, idempotency_key: str, owner_scope: str) -> str:
        digest = hashlib.sha256(
            f"{owner_scope}\0{template_id}\0{idempotency_key}".encode("utf-8")
        ).hexdigest()[:32]
        return f"agent-provision:{digest}"

    def _advance(self, job: InstallationJob, status: InstallationStatus, *, runtime_id: str | None = None,
                 error_summary: str | None = None) -> InstallationJob:
        updated = job.advance(status, runtime_id=runtime_id, error_summary=error_summary)
        try:
            return self.jobs.update(updated)
        except Exception:
            if self.jobs.get(job.job_id) == updated:
                return updated
            raise

    def _job(self, job_id: str, owner_scope: str) -> InstallationJob:
        job = self.jobs.get(job_id)
        if job.owner_scope != owner_scope:
            raise KeyError(f"unknown installation job: {job_id}")
        return job

    def _ref_for_job(self, job: InstallationJob) -> AgentRegistrationRef:
        if not job.runtime_id:
            raise ValueError("agent installation has no instance resource")
        for registration in self.pool.registry.registrations():
            if registration.ref.resource_id == job.runtime_id:
                return registration.ref
        raise ValueError("agent instance is unavailable and requires reconciliation")

    def _check_dependencies(self, template: AgentTemplate) -> None:
        for resource_id in template.dependencies:
            resource = self.pool.resource_plane.runtime(resource_id)
            health = self.pool.resource_plane.health_monitor.health(resource_id)
            if not resource.enabled or resource.draining or not health.healthy:
                raise ValueError("agent template dependency is not available")

    def _drain(self, ref: AgentRegistrationRef) -> None:
        plane = self.pool.resource_plane
        current = plane.runtime(ref.resource_id)
        plane.set_agent_instance_state(ref, expected_version=current.version, enabled=False, draining=True)

    def _refresh(self) -> None:
        if self.refresh_runtime is not None:
            self.refresh_runtime()

    def _active_or_unknown(self, ref: AgentRegistrationRef) -> bool:
        if self.coordinator.active_slots(ref.resource_id) > 0:
            return True
        try:
            profile = self.pool.resource_plane.runtime(ref.resource_id)
        except KeyError:
            return False
        return bool(profile.metadata.get("outcomeUnknown"))

    def _dispose(self, agent: BaseAgent) -> None:
        for name in ("dispose", "close"):
            method = getattr(agent, name, None)
            if callable(method):
                method()
                return

    def provision(self, template_id: str, idempotency_key: str, owner_scope: str = "local") -> InstallationJob:
        scope = self._scope(owner_scope)
        key = str(idempotency_key or "").strip()
        template_id = str(template_id or "").strip()
        if not key:
            raise ValueError("idempotency key must not be blank")
        with self._lock:
            try:
                template = self._templates[template_id]
            except KeyError as exc:
                raise KeyError(template_id) from exc
            job_id = self._job_id(template_id, key, scope)
            try:
                previous = self._job(job_id, scope)
            except KeyError:
                previous = None
            if previous is not None:
                if previous.status is InstallationStatus.RUNNING:
                    current = self.pool.describe(self._ref_for_job(previous))
                    if not current.resource.enabled or current.draining or not current.logical_enabled:
                        raise ValueError("agent installation requires reconciliation")
                if previous.status in {InstallationStatus.QUEUED, InstallationStatus.INSTALLING,
                                       InstallationStatus.REGISTERING, InstallationStatus.UNINSTALLING}:
                    raise ValueError("agent installation requires reconciliation")
                return previous
            registrations = self.pool.registry.registrations()
            if not any(item.definition == template.definition for item in registrations):
                raise ValueError("agent template definition is no longer registered")
            resource_ids = {profile.runtime_id for profile in self.pool.resource_plane.runtimes()}
            existing = [job for job in self.jobs.list(scope)
                        if self.owns(job) and job.catalog_id == f"agent:{template_id}"
                        and (job.status not in {InstallationStatus.FAILED, InstallationStatus.REMOVED}
                             or (job.status is InstallationStatus.FAILED and job.runtime_id is not None
                                 and job.runtime_id in resource_ids))]
            if len(existing) >= template.max_instances:
                raise ValueError("agent template instance capacity exhausted")
            job = self.jobs.create(InstallationJob.new(
                job_id, f"agent:{template_id}", scope,
                display_name=template.definition.agent_name,
            ))
            created: BaseAgent | None = None
            ref: AgentRegistrationRef | None = None
            instance_id = f"agent:{template_id}:{job_id.rsplit(':', 1)[-1]}"
            registry_epoch = registrations[0].ref.registry_id
            stage = "template construction"
            try:
                job = self._advance(job, InstallationStatus.INSTALLING)
                self._check_dependencies(template)
                if not self.pool.registry.is_enabled(template.definition.agent_id):
                    raise ValueError("logical Agent is disabled")
                candidate = template.factory()
                if not isinstance(candidate, BaseAgent):
                    raise ValueError("agent template factory did not return a BaseAgent")
                if (any(candidate is seed for seed in self._seeds)
                        or any(item.implementation is candidate for item in self.pool.registry.registrations())):
                    raise ValueError("agent template factory returned an already registered object")
                created = candidate
                if self.pool.registry.definition_for(candidate) != template.definition or not candidate.profile.enabled:
                    raise ValueError("agent template factory declaration does not match its approved definition")
                stage = "instance registration"
                ref = self.pool.register_instance(candidate, instance_id=instance_id, enabled=False)
                job = self._advance(job, InstallationStatus.REGISTERING, runtime_id=ref.resource_id)
                stage = "instance health check"
                self._check_dependencies(template)
                if template.health_check is not None and template.health_check(candidate) is not True:
                    raise ValueError("agent template health check failed")
                current = self.pool.describe(ref)
                self.pool.heartbeat(ref)
                stage = "instance publication"
                self.pool.update(ref, expected_version=current.resource.version, enabled=True, draining=False)
                self._refresh()
                return self._advance(job, InstallationStatus.RUNNING, runtime_id=ref.resource_id)
            except Exception as exc:
                # Enabling and job persistence can commit before their ACK is
                # lost. Read both facts before any compensation.
                latest = self.jobs.get(job.job_id)
                if ref is None and created is not None:
                    # Fact publication precedes Registry publication. A lost
                    # acknowledgement can leave this request's disabled fact.
                    ref = next((profile.agent_registration for profile in self.pool.resource_plane.runtimes()
                                if profile.agent_registration is not None
                                and profile.agent_registration.instance_id == instance_id
                                and profile.agent_registration.registry_id == registry_epoch
                                and profile.agent_registration.definition_digest == template.definition.digest), None)
                if ref is not None:
                    current = self.pool.resource_plane.runtime(ref.resource_id)
                    if (latest.status is InstallationStatus.RUNNING
                            and current.enabled and not current.draining):
                        return latest
                if latest.status is InstallationStatus.RUNNING:
                    raise ValueError("agent publication requires reconciliation") from exc
                safe_to_dispose = ref is None
                if ref is not None:
                    try:
                        self._drain(ref)
                        if not self._active_or_unknown(ref):
                            current = self.pool.resource_plane.runtime(ref.resource_id)
                            try:
                                self.pool.registry.get_registration(ref)
                            except AgentNotFound:
                                self.pool.resource_plane.unregister_agent_instance(ref)
                            else:
                                self.pool.unregister(ref, expected_version=current.version)
                            safe_to_dispose = True
                            self._refresh()
                    except Exception:
                        pass  # Keep confirmed withdrawal even if host refresh failed.
                if created is not None and safe_to_dispose:
                    try:
                        self._dispose(created)
                    except Exception:
                        pass
                summary = f"{stage} failed ({type(exc).__name__})"
                return self._advance(latest, InstallationStatus.FAILED, error_summary=summary,
                                     runtime_id=ref.resource_id if ref is not None and not safe_to_dispose else None)

    def instances(self, owner_scope: str = "local") -> list[dict]:
        scope = self._scope(owner_scope)
        result = []
        for job in self.jobs.list(scope):
            if not self.owns(job):
                continue
            try:
                item = self.pool.describe(self._ref_for_job(job))
            except (KeyError, ValueError):
                item = None
            result.append({
                "jobId": job.job_id,
                "templateId": str(job.catalog_id)[len("agent:"):],
                "instanceId": item.ref.instance_id if item else None,
                "agentId": item.ref.agent_id if item else None,
                "resourceId": job.runtime_id,
                "status": job.status.value,
                "enabled": item.resource.enabled if item else False,
                "draining": item.resource.draining if item else False,
                "healthy": item.health.healthy if item else False,
                "callable": bool(job.status is InstallationStatus.RUNNING
                                 and item and item.logical_enabled and item.resource.enabled
                                 and not item.draining and item.health.healthy),
                "reconciliationRequired": bool(
                    (item is None and job.status not in {InstallationStatus.REMOVED, InstallationStatus.FAILED})
                    or job.status in {InstallationStatus.QUEUED, InstallationStatus.INSTALLING,
                                      InstallationStatus.REGISTERING, InstallationStatus.UNINSTALLING}
                    or (item is not None and (item.resource.metadata.get("outcomeUnknown")
                                             or job.status is InstallationStatus.FAILED))),
            })
        return result

    def stop(self, job_id: str, owner_scope: str = "local") -> InstallationJob:
        scope = self._scope(owner_scope)
        with self._lock:
            job = self._job(job_id, scope)
            if not self.owns(job):
                raise KeyError(job_id)
            if job.status is InstallationStatus.STOPPED:
                return job
            if job.status is not InstallationStatus.RUNNING:
                raise ValueError("only running agent installations can be stopped")
            ref = self._ref_for_job(job)
            self._drain(ref)
            self._refresh()
            return self._advance(job, InstallationStatus.STOPPED)

    def uninstall(self, job_id: str, owner_scope: str = "local") -> InstallationJob:
        scope = self._scope(owner_scope)
        with self._lock:
            job = self._job(job_id, scope)
            if job.status is InstallationStatus.RUNNING:
                job = self.stop(job_id, owner_scope=scope)
            if job.status is InstallationStatus.REMOVED:
                return job
            if not self.owns(job):
                raise KeyError(job_id)
            if job.status not in {InstallationStatus.STOPPED, InstallationStatus.FAILED}:
                raise ValueError("only stopped or failed agent installations can be uninstalled")
            if job.runtime_id is None:
                return self._advance(self._advance(job, InstallationStatus.UNINSTALLING), InstallationStatus.REMOVED)
            if job.status is InstallationStatus.FAILED:
                try:
                    self.pool.resource_plane.runtime(job.runtime_id)
                except KeyError:
                    if not any(item.ref.resource_id == job.runtime_id for item in self.pool.registry.registrations()):
                        return self._advance(self._advance(job, InstallationStatus.UNINSTALLING), InstallationStatus.REMOVED)
            ref = self._ref_for_job(job)
            self._drain(ref)
            if self._active_or_unknown(ref):
                raise ValueError("agent instance still has active or unknown work")
            registration = self.pool.registry.get_registration(ref)
            current = self.pool.describe(ref)
            job = self._advance(job, InstallationStatus.UNINSTALLING)
            try:
                self.pool.unregister(ref, expected_version=current.resource.version)
                self._dispose(registration.implementation)
                self._refresh()
                return self._advance(job, InstallationStatus.REMOVED)
            except Exception as exc:
                return self._advance(job, InstallationStatus.FAILED,
                                     error_summary=f"agent instance cleanup failed ({type(exc).__name__})")


__all__ = ["AgentProvisioner", "AgentTemplate"]
