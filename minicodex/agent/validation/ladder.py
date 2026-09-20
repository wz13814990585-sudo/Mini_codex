"""Select verification by artifact and risk before applying mode budgets."""
from dataclasses import dataclass
from .plan import EvidenceStrength
from .evidence import ValidationPurpose


@dataclass(frozen=True)
class VerificationRung:
    strength: EvidenceStrength
    reason: str
    command: str = ""
    purpose: ValidationPurpose = ValidationPurpose.REGRESSION
    capability: str = "test.run"


class VerificationLadder:
    def select(self, profile, paths, request="", *, mode=None, impact=None):
        docs = paths and all(p.lower().endswith((".md", ".txt", ".rst")) for p in paths)
        result = [VerificationRung(EvidenceStrength.STRUCTURE, "检查已变更产物的内容与语法",
                                  purpose=ValidationPurpose.ACCEPTANCE, capability="validation.structure")]
        if docs:
            return tuple(result)
        commands = dict(profile.commands)
        for category in ("lint", "typecheck"):
            if category in commands:
                result.append(VerificationRung(EvidenceStrength.LINT, f"观察到 {category} 配置", commands[category], capability="process.run"))
        result.append(VerificationRung(EvidenceStrength.TARGETED, "独立证明每项请求行为",
                                      purpose=ValidationPurpose.ACCEPTANCE, capability="validation.behavior"))
        risk = any(word in (" ".join(paths) + " " + request).casefold() for word in ("auth", "security", "payment", "migration", "dependency", "package.json"))
        impacted = bool(getattr(impact, "dependents", ()) or getattr(impact, "tests", ()))
        has_regression_target = bool(commands.get("test") or getattr(impact, "tests", ()))
        if risk or (has_regression_target and (len(paths) > 1 or impacted)):
            result.append(VerificationRung(EvidenceStrength.REGRESSION, "风险或跨文件影响需要附近回归验证", commands.get("test", ""), capability="test.run"))
        if "build" in commands:
            result.append(VerificationRung(EvidenceStrength.BUILD, "项目声明了构建命令", commands["build"], capability="process.run"))
        request_lower = request.casefold()
        if any(w in request_lower for w in ("game", "click", "playable", "keypress", "keyboard", "交互")):
            result.append(VerificationRung(EvidenceStrength.RUNTIME, "请求了可观测的浏览器行为",
                                          purpose=ValidationPurpose.ACCEPTANCE, capability="validation.browser"))
        elif any(w in request_lower for w in ("api", "server", "http", "endpoint", "login")):
            result.append(VerificationRung(EvidenceStrength.RUNTIME, "请求了可观测的 API 行为",
                                          purpose=ValidationPurpose.ACCEPTANCE, capability="service.validate"))
        if any(w in request.casefold() for w in ("repository-wide", "full regression")):
            result.append(VerificationRung(EvidenceStrength.FULL, "明确请求了广度回归", commands.get("test", ""), capability="test.run"))
        return tuple(result)
