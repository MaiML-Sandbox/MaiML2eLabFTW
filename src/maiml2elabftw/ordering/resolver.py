from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from ..core.errors import ConversionError, ErrorCode
from ..core.models import (
    InstructionDefinition,
    MethodProtocolModel,
    PnmlGraph,
    StepDefinition,
    StepOrderSource,
    StepPlan,
)


@dataclass(frozen=True)
class TransitionOrder:
    transition_id: str
    instruction_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class StepOrderOverride:
    document_uuid: str
    method_uuid: str
    steps: tuple[TransitionOrder, ...]


class PnmlOrderResolver:
    """Resolve only unambiguous linear PNML or a fully validated override."""

    def resolve(
        self,
        method: MethodProtocolModel,
        override: StepOrderOverride | None = None,
    ) -> StepPlan:
        all_instructions = tuple(item for program in method.programs for item in program.instructions)
        instructions = {item.instruction_id: item for item in all_instructions}
        if len(instructions) != len(all_instructions):
            raise ConversionError(ErrorCode.DUPLICATE_ID, "instruction IDs must be unique within a method")
        by_transition = self._instructions_by_transition(all_instructions)
        graphs = method.pnml_graphs
        if not graphs:
            raise ConversionError(ErrorCode.INVALID_PNML, "method has no PNML")
        known_transitions = {node.transition_id for graph in graphs for node in graph.transitions}
        unknown_refs = sorted(set(by_transition) - known_transitions)
        if unknown_refs:
            raise ConversionError(
                ErrorCode.BROKEN_REFERENCE,
                "instruction refers to an unknown transition",
                {"transition_ids": unknown_refs},
            )

        if override is not None:
            graph = self._merge_graphs(graphs)
            order = self._validate_override(method, graph, override, instructions, by_transition)
            source = StepOrderSource.YAML
        else:
            if len(graphs) != 1:
                raise ConversionError(
                    ErrorCode.AMBIGUOUS_STEP_ORDER,
                    "multiple PNML graphs require a Step order override",
                    {"pnml_count": len(graphs)},
                )
            transition_ids = self._resolve_linear(graphs[0])
            order = tuple(TransitionOrder(tid, ()) for tid in transition_ids)
            source = StepOrderSource.PNML

        return StepPlan(source=source, steps=self._expand(order, by_transition, instructions, override is not None))

    @staticmethod
    def _merge_graphs(graphs: tuple[PnmlGraph, ...]) -> PnmlGraph:
        places = tuple(node for graph in graphs for node in graph.places)
        transitions = tuple(node for graph in graphs for node in graph.transitions)
        arcs = tuple(edge for graph in graphs for edge in graph.arcs)
        identifiers = [node.place_id for node in places] + [node.transition_id for node in transitions]
        if len(identifiers) != len(set(identifiers)):
            raise ConversionError(ErrorCode.DUPLICATE_ID, "PNML node IDs must be unique within a method")
        return PnmlGraph(places, transitions, arcs)

    @staticmethod
    def _instructions_by_transition(
        instructions: tuple[InstructionDefinition, ...],
    ) -> dict[str, tuple[str, ...]]:
        result: dict[str, list[str]] = defaultdict(list)
        for instruction in instructions:
            for transition_id in instruction.transition_refs:
                result[transition_id].append(instruction.instruction_id)
        return {key: tuple(value) for key, value in result.items()}

    def _resolve_linear(self, graph: PnmlGraph) -> tuple[str, ...]:
        places = {node.place_id for node in graph.places}
        transitions = {node.transition_id for node in graph.transitions}
        all_nodes = places | transitions
        if not transitions:
            raise ConversionError(ErrorCode.INVALID_PNML, "PNML has no transitions")

        outgoing: dict[str, list[str]] = defaultdict(list)
        incoming: dict[str, list[str]] = defaultdict(list)
        for arc in graph.arcs:
            if arc.source_id not in all_nodes or arc.target_id not in all_nodes:
                raise ConversionError(ErrorCode.BROKEN_REFERENCE, f"arc {arc.arc_id} refers to an unknown node")
            if (arc.source_id in places) == (arc.target_id in places):
                raise ConversionError(ErrorCode.INVALID_PNML, f"arc {arc.arc_id} does not alternate place/transition")
            outgoing[arc.source_id].append(arc.target_id)
            incoming[arc.target_id].append(arc.source_id)

        # A PLACE that connects to more than one *distinct* transition on
        # either side is a genuine fork or merge point: the graph alone
        # can't tell whether those transitions run in some order, in
        # parallel, or as alternatives, so an explicit Step order override
        # is required instead of guessing (see test_branch_is_not_linearized).
        # This check is deliberately about places only. A single transition
        # with several places attached - e.g. a measurement step that reads
        # a sample *and* a condition and writes a result *and* the measured
        # sample, all in one step - is not a sequencing choice, just several
        # resources on one step. A transition's own arc count says nothing
        # about ambiguity by itself, so it is not checked here.
        for place in places:
            if len(set(outgoing[place])) > 1 or len(set(incoming[place])) > 1:
                raise ConversionError(ErrorCode.AMBIGUOUS_STEP_ORDER, "PNML contains a branch, merge, or parallel path")

        # Reduce to a transition-level precedence graph: a place produced by
        # one transition and consumed by another orders those two
        # transitions. A place that is purely an input (no producer
        # transition - e.g. a starting sample) or purely an output (no
        # consumer transition - e.g. a final result) is a boundary resource,
        # not a sequencing edge, and creates no ordering constraint no
        # matter how many such places one transition has. This is what lets
        # a single-transition PNML with several input/output places resolve
        # trivially, instead of being rejected as "ambiguous" for having
        # more than one place attached to its one transition.
        next_transition: dict[str, str] = {}
        prev_transition: dict[str, str] = {}
        for place in places:
            producer = incoming[place][0] if incoming[place] else None
            consumer = outgoing[place][0] if outgoing[place] else None
            if producer is None or consumer is None:
                continue
            if producer in next_transition and next_transition[producer] != consumer:
                raise ConversionError(ErrorCode.AMBIGUOUS_STEP_ORDER, "PNML contains a branch, merge, or parallel path")
            if consumer in prev_transition and prev_transition[consumer] != producer:
                raise ConversionError(ErrorCode.AMBIGUOUS_STEP_ORDER, "PNML contains a branch, merge, or parallel path")
            next_transition[producer] = consumer
            prev_transition[consumer] = producer

        starts = [transition for transition in transitions if transition not in prev_transition]
        ends = [transition for transition in transitions if transition not in next_transition]
        if len(starts) != 1 or len(ends) != 1:
            raise ConversionError(ErrorCode.AMBIGUOUS_STEP_ORDER, "PNML start/end is not unique")

        seen: set[str] = set()
        transition_order: list[str] = []
        current: str | None = starts[0]
        while current is not None:
            if current in seen:
                raise ConversionError(ErrorCode.PNML_CYCLE, "PNML contains a cycle")
            seen.add(current)
            transition_order.append(current)
            current = next_transition.get(current)

        if set(transition_order) != transitions:
            raise ConversionError(ErrorCode.AMBIGUOUS_STEP_ORDER, "not all transitions are reachable in one linear path")
        return tuple(transition_order)

    def _validate_override(
        self,
        method: MethodProtocolModel,
        graph: PnmlGraph,
        override: StepOrderOverride,
        instructions: dict[str, InstructionDefinition],
        by_transition: dict[str, tuple[str, ...]],
    ) -> tuple[TransitionOrder, ...]:
        if (override.document_uuid, override.method_uuid) != method.source.duplicate_key:
            raise ConversionError(ErrorCode.ORDER_SOURCE_MISMATCH, "override UUIDs do not match the method")
        expected = {node.transition_id for node in graph.transitions}
        supplied = [item.transition_id for item in override.steps]
        if len(supplied) != len(set(supplied)) or set(supplied) != expected:
            raise ConversionError(ErrorCode.INVALID_ORDER_FILE, "override must contain every transition exactly once")
        for item in override.steps:
            linked = set(by_transition.get(item.transition_id, ()))
            requested = set(item.instruction_ids)
            if item.instruction_ids and (requested != linked or any(key not in instructions for key in requested)):
                raise ConversionError(ErrorCode.INVALID_ORDER_FILE, f"instruction list does not match {item.transition_id}")
        return override.steps

    def _expand(
        self,
        order: tuple[TransitionOrder, ...],
        by_transition: dict[str, tuple[str, ...]],
        instructions: dict[str, InstructionDefinition],
        has_override: bool,
    ) -> tuple[StepDefinition, ...]:
        occurrences: Counter[str] = Counter()
        result: list[StepDefinition] = []
        for transition in order:
            linked = by_transition.get(transition.transition_id, ())
            if not linked:
                raise ConversionError(ErrorCode.MISSING_INSTRUCTION, f"{transition.transition_id} has no instruction")
            if len(linked) > 1 and not transition.instruction_ids and not has_override:
                raise ConversionError(
                    ErrorCode.AMBIGUOUS_INSTRUCTION_ORDER,
                    f"{transition.transition_id} has multiple instructions; provide an override",
                )
            instruction_ids = transition.instruction_ids or linked
            for instruction_id in instruction_ids:
                instruction = instructions[instruction_id]
                occurrences[instruction_id] += 1
                result.append(
                    StepDefinition(
                        ordinal=len(result) + 1,
                        transition_id=transition.transition_id,
                        instruction_id=instruction_id,
                        title=instruction.title,
                        body=instruction.body,
                        occurrence=occurrences[instruction_id],
                    )
                )
        return tuple(result)
