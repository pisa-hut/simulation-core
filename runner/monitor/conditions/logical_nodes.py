from .condition_node import ConditionNode
from .evaluation import ConditionCode


class AndNode(ConditionNode):
    def __init__(self, config: dict, children: list[ConditionNode]):
        super().__init__(config)
        if self.node_type != "and":
            raise ValueError(f"AndNode expects type='and', got: {self.node_type}")
        if not children:
            raise ValueError("AndNode must have at least one child")
        self.children = children

    def put(self, data):
        for child in self.children:
            child.put(data)

    def evaluate(self):
        saw_not_evaluated = None

        for child in self.children:
            result = child.evaluate()

            if result.code == ConditionCode.NOT_TRIGGERED:
                return self.result(
                    ConditionCode.NOT_TRIGGERED,
                    f"{result.condition_name} not triggered: {result.detail}",
                )

            if result.code == ConditionCode.NOT_EVALUATED:
                saw_not_evaluated = result

        if saw_not_evaluated is not None:
            return self.result(
                ConditionCode.NOT_EVALUATED,
                f"{saw_not_evaluated.condition_name} not evaluated: {saw_not_evaluated.detail}",
            )

        return self.result(
            ConditionCode.TRIGGERED,
            "All conditions triggered",
        )

    def __str__(self):
        return f"and:{self.name}({', '.join(str(c) for c in self.children)})"


class OrNode(ConditionNode):
    def __init__(self, config: dict, children: list[ConditionNode]):
        super().__init__(config)
        if self.node_type != "or":
            raise ValueError(f"OrNode expects type='or', got: {self.node_type}")
        if not children:
            raise ValueError("OrNode must have at least one child")
        self.children = children

    def put(self, data):
        for child in self.children:
            child.put(data)

    def evaluate(self):
        saw_not_evaluated = None

        for child in self.children:
            result = child.evaluate()

            if result.code == ConditionCode.TRIGGERED:
                return self.result(
                    ConditionCode.TRIGGERED,
                    f"{result.condition_name} triggered: {result.detail}",
                )

            if result.code == ConditionCode.NOT_EVALUATED:
                saw_not_evaluated = result

        if saw_not_evaluated is not None:
            return self.result(
                ConditionCode.NOT_EVALUATED,
                f"{saw_not_evaluated.condition_name} not evaluated: {saw_not_evaluated.detail}",
            )

        return self.result(
            ConditionCode.NOT_TRIGGERED,
            "No conditions triggered",
        )

    def __str__(self):
        return f"or:{self.name}({', '.join(str(c) for c in self.children)})"
