from abc import ABC, abstractmethod

from .evaluation import ConditionCode, EvaluationResult

TEST_OUTCOME_ALIASES = {
    "success": "success",
    "succeed": "success",
    "pass": "success",
    "passed": "success",
    "ok": "success",
    "fail": "fail",
    "failure": "fail",
    "failed": "fail",
    "invalid": "invalid",
}


class ConditionNode(ABC):
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        original_reset = cls.__dict__.get("reset")
        if original_reset is None or getattr(original_reset, "_delay_wrapped", False):
            return

        def reset_with_delay_clear(self, *args, **kwargs):
            result = original_reset(self, *args, **kwargs)
            ConditionNode.reset_delay(self)
            return result

        reset_with_delay_clear._delay_wrapped = True
        cls.reset = reset_with_delay_clear

    def __init__(self, config: dict):
        if "type" not in config:
            raise ValueError(f"Missing 'type' in config: {config}")
        self.node_type = config["type"].lower()
        self.name = config.get("name", self.node_type)
        self.test_outcome = self._parse_test_outcome(config)
        self.context = config.get("_context", {})
        self.delay_ns = self._parse_delay_ns(config)
        self._delay_started_at_ns: int | None = None
        self._delay_original_detail: str = ""
        self._delay_test_outcome: str | None = None
        self._delay_trigger_name: str | None = None

    @abstractmethod
    def put(self, data):
        pass

    @abstractmethod
    def evaluate(self) -> EvaluationResult:
        pass

    @abstractmethod
    def reset(self):
        pass

    def result(
        self,
        code: ConditionCode,
        detail: str = "",
        *,
        test_outcome: str | None = None,
        trigger_name: str | None = None,
    ) -> EvaluationResult:
        effective_test_outcome = test_outcome if test_outcome is not None else self.test_outcome
        effective_trigger_name = trigger_name if trigger_name is not None else self.name
        if self.delay_ns > 0:
            delayed_result = self._apply_delay(
                code,
                detail,
                test_outcome=effective_test_outcome,
                trigger_name=effective_trigger_name,
            )
            if delayed_result is not None:
                return delayed_result

        return EvaluationResult(
            condition_name=self.name,
            code=code,
            detail=detail,
            test_outcome=effective_test_outcome,
            trigger_name=effective_trigger_name,
        )

    def reset_delay(self) -> None:
        self._delay_started_at_ns = None
        self._delay_original_detail = ""
        self._delay_test_outcome = None
        self._delay_trigger_name = None

    def _apply_delay(
        self,
        code: ConditionCode,
        detail: str,
        *,
        test_outcome: str | None,
        trigger_name: str,
    ) -> EvaluationResult | None:
        current_time_ns = self._current_sim_time_ns()
        if current_time_ns is None:
            if code == ConditionCode.TRIGGERED:
                return EvaluationResult(
                    condition_name=self.name,
                    code=ConditionCode.NOT_EVALUATED,
                    detail=(
                        "Condition triggered but delay cannot start because current "
                        "simulation time is unavailable"
                    ),
                    test_outcome=test_outcome,
                    trigger_name=trigger_name,
                )
            return None

        if code == ConditionCode.TRIGGERED and self._delay_started_at_ns is None:
            self._delay_started_at_ns = current_time_ns
            self._delay_original_detail = detail
            self._delay_test_outcome = test_outcome
            self._delay_trigger_name = trigger_name

        if self._delay_started_at_ns is None:
            return None

        elapsed_ns = current_time_ns - self._delay_started_at_ns
        if elapsed_ns >= self.delay_ns:
            return EvaluationResult(
                condition_name=self.name,
                code=ConditionCode.TRIGGERED,
                detail=(
                    f"Delay satisfied after {elapsed_ns / 1e6:.3f} ms "
                    f"(configured delay={self.delay_ns / 1e6:.3f} ms, "
                    f"started_at={self._delay_started_at_ns / 1e6:.3f} ms, "
                    f"triggered_at={current_time_ns / 1e6:.3f} ms). "
                    f"Original trigger: {self._delay_original_detail}"
                ),
                test_outcome=self._delay_test_outcome,
                trigger_name=self._delay_trigger_name,
            )

        remaining_ns = self.delay_ns - elapsed_ns
        return EvaluationResult(
            condition_name=self.name,
            code=ConditionCode.NOT_TRIGGERED,
            detail=(
                f"Delay pending for condition '{self.name}': "
                f"elapsed={elapsed_ns / 1e6:.3f} ms, "
                f"remaining={remaining_ns / 1e6:.3f} ms, "
                f"configured delay={self.delay_ns / 1e6:.3f} ms. "
                f"Original trigger: {self._delay_original_detail}"
            ),
            test_outcome=self._delay_test_outcome,
            trigger_name=self._delay_trigger_name,
        )

    def _current_sim_time_ns(self) -> int | None:
        if not isinstance(self.context, dict):
            return None
        raw_time = self.context.get("current_sim_time_ns")
        if raw_time is None:
            return None
        return int(raw_time)

    @staticmethod
    def _parse_test_outcome(config: dict) -> str | None:
        raw_outcome = config.get(
            "test_outcome",
            config.get("outcome", config.get("result_status", config.get("result"))),
        )
        if raw_outcome is None:
            return None

        normalized = str(raw_outcome).strip().lower()
        try:
            return TEST_OUTCOME_ALIASES[normalized]
        except KeyError as exc:
            raise ValueError(
                "Condition result status must be one of Success, Fail, or Invalid, "
                f"but got: {raw_outcome!r}"
            ) from exc

    @staticmethod
    def _parse_delay_ns(config: dict) -> int:
        configured_keys = [key for key in ("delay_ns", "delay_ms", "delay_s") if key in config]
        if len(configured_keys) > 1:
            keys = ", ".join(configured_keys)
            raise ValueError(f"Condition delay must use only one key; got: {keys}")
        if not configured_keys:
            return 0

        key = configured_keys[0]
        try:
            value = float(config[key])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Condition config '{key}' must be a number") from exc
        if value < 0:
            raise ValueError(f"Condition config '{key}' must be >= 0")
        if key == "delay_ns":
            return int(value)
        if key == "delay_ms":
            return int(value * 1e6)
        return int(value * 1e9)
