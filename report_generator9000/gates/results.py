"""What a gate reports: the rule that failed, and the artifact it failed on."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Violation:
    gate: str
    rule: str
    artifact: str
    detail: str

    def format(self) -> str:
        return f"  {self.rule}\t{self.artifact}\t{self.detail}"


@dataclass(frozen=True)
class GateResult:
    gate: str
    violations: tuple[Violation, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.violations

    def format(self) -> str:
        if self.passed:
            return f"GATE {self.gate}: PASS"
        count = len(self.violations)
        noun = "violation" if count == 1 else "violations"
        lines = [f"GATE {self.gate}: FAIL ({count} {noun})"]
        lines.extend(violation.format() for violation in self.violations)
        return "\n".join(lines)


@dataclass(frozen=True)
class GateReport:
    results: tuple[GateResult, ...]

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.results)

    @property
    def violations(self) -> tuple[Violation, ...]:
        return tuple(
            violation
            for result in self.results
            for violation in result.violations
        )

    def format(self) -> str:
        lines = [result.format() for result in self.results]
        failed = [result for result in self.results if not result.passed]
        total = len(self.results)
        if not failed:
            lines.append(f"PASSED {total} of {total} gates")
        else:
            count = len(self.violations)
            noun = "violation" if count == 1 else "violations"
            lines.append(
                f"FAILED {len(failed)} of {total} gates, {count} {noun}"
            )
        return "\n".join(lines)


def result(gate: str, violations: list[Violation]) -> GateResult:
    return GateResult(gate=gate, violations=tuple(violations))


def violation(gate: str, rule: str, artifact: str, detail: str) -> Violation:
    return Violation(gate=gate, rule=rule, artifact=artifact, detail=detail)
