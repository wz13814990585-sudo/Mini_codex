"""Select verification by artifact and risk before applying mode budgets."""
from dataclasses import dataclass
from .plan import EvidenceStrength


@dataclass(frozen=True)
class VerificationRung:
    strength: EvidenceStrength
    reason: str
    command: str = ""


class VerificationLadder:
    def select(self, profile, paths, request=""):
        docs = paths and all(p.lower().endswith((".md", ".txt", ".rst")) for p in paths)
        result = [VerificationRung(EvidenceStrength.STRUCTURE, "Check changed artifact content and syntax")]
        if docs:
            return tuple(result)
        commands = dict(profile.commands)
        for category in ("lint", "typecheck"):
            if category in commands:
                result.append(VerificationRung(EvidenceStrength.LINT, f"Observed {category} configuration", commands[category]))
        result.append(VerificationRung(EvidenceStrength.TARGETED, "Prove each requested behavior independently"))
        risk = any(word in (" ".join(paths) + " " + request).casefold() for word in ("auth", "security", "payment", "migration", "dependency", "package.json"))
        if risk or len(paths) > 1:
            result.append(VerificationRung(EvidenceStrength.REGRESSION, "Risk or cross-file impact requires nearby regression", commands.get("test", "")))
        if "build" in commands:
            result.append(VerificationRung(EvidenceStrength.BUILD, "Project declares a build command", commands["build"]))
        if any(w in request.casefold() for w in ("api", "server", "game", "click", "playable")):
            result.append(VerificationRung(EvidenceStrength.RUNTIME, "Requested observable runtime behavior"))
        if any(w in request.casefold() for w in ("repository-wide", "full regression")):
            result.append(VerificationRung(EvidenceStrength.FULL, "Broad regression explicitly requested", commands.get("test", "")))
        return tuple(result)
