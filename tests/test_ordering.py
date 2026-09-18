import unittest

from maiml2elabftw.core.errors import ConversionError, ErrorCode
from maiml2elabftw.core.models import (
    ArcEdge,
    InstructionDefinition,
    MethodProtocolModel,
    PlaceNode,
    PnmlGraph,
    ProgramDefinition,
    SourceIdentity,
    SourceRef,
    StepOrderSource,
    TransitionNode,
)
from maiml2elabftw.ordering import PnmlOrderResolver, StepOrderOverride, TransitionOrder


def ref(kind: str, element_id: str) -> SourceRef:
    return SourceRef(kind, element_id)


def graph(arcs: list[tuple[str, str]]) -> PnmlGraph:
    places = tuple(PlaceNode(pid, ref("place", pid)) for pid in ("p0", "p1", "p2"))
    transitions = tuple(TransitionNode(tid, ref("transition", tid)) for tid in ("t1", "t2"))
    edges = tuple(ArcEdge(f"a{i}", source, target, ref("arc", f"a{i}")) for i, (source, target) in enumerate(arcs))
    return PnmlGraph(places, transitions, edges)


def custom_graph(place_ids: tuple[str, ...], transition_ids: tuple[str, ...], arcs: list[tuple[str, str]]) -> PnmlGraph:
    """Like ``graph()`` but with an arbitrary set of place/transition ids,
    for shapes the fixed 3-place/2-transition helper can't express."""
    places = tuple(PlaceNode(pid, ref("place", pid)) for pid in place_ids)
    transitions = tuple(TransitionNode(tid, ref("transition", tid)) for tid in transition_ids)
    edges = tuple(ArcEdge(f"a{i}", source, target, ref("arc", f"a{i}")) for i, (source, target) in enumerate(arcs))
    return PnmlGraph(places, transitions, edges)


def instruction(iid: str, *transition_refs: str) -> InstructionDefinition:
    return InstructionDefinition(iid, iid.upper(), f"body:{iid}", transition_refs, ref("instruction", iid))


def method(pnml: PnmlGraph, instructions: tuple[InstructionDefinition, ...]) -> MethodProtocolModel:
    program = ProgramDefinition("program", None, None, instructions, (), ref("program", "program"))
    return MethodProtocolModel(
        SourceIdentity("doc", "method"), "Method", None, ref("method", "method"), (program,), (pnml,)
    )


LINEAR = [("p0", "t1"), ("t1", "p1"), ("p1", "t2"), ("t2", "p2")]


class OrderingTests(unittest.TestCase):
    def test_resolves_linear_pnml(self) -> None:
        plan = PnmlOrderResolver().resolve(method(graph(LINEAR), (instruction("i1", "t1"), instruction("i2", "t2"))))
        self.assertIs(plan.source, StepOrderSource.PNML)
        self.assertEqual([(s.transition_id, s.instruction_id) for s in plan.steps], [("t1", "i1"), ("t2", "i2")])

    def test_repeated_instruction_creates_one_step_at_each_transition(self) -> None:
        plan = PnmlOrderResolver().resolve(method(graph(LINEAR), (instruction("i1", "t1", "t2"),)))
        self.assertEqual([step.occurrence for step in plan.steps], [1, 2])

    def test_branch_is_not_linearized(self) -> None:
        branching = graph([("p0", "t1"), ("t1", "p1"), ("p1", "t2"), ("p0", "t2"), ("t2", "p2")])
        with self.assertRaises(ConversionError) as caught:
            PnmlOrderResolver().resolve(method(branching, (instruction("i1", "t1"), instruction("i2", "t2"))))
        self.assertIs(caught.exception.code, ErrorCode.AMBIGUOUS_STEP_ORDER)

    def test_cycle_is_rejected(self) -> None:
        cyclic = graph([("p0", "t1"), ("t1", "p1"), ("p1", "t2"), ("t2", "p0")])
        with self.assertRaises(ConversionError) as caught:
            PnmlOrderResolver().resolve(method(cyclic, (instruction("i1", "t1"), instruction("i2", "t2"))))
        self.assertIn(caught.exception.code, {ErrorCode.PNML_CYCLE, ErrorCode.AMBIGUOUS_STEP_ORDER})

    def test_missing_instruction_is_rejected(self) -> None:
        with self.assertRaises(ConversionError) as caught:
            PnmlOrderResolver().resolve(method(graph(LINEAR), (instruction("i1", "t1"),)))
        self.assertIs(caught.exception.code, ErrorCode.MISSING_INSTRUCTION)

    def test_override_controls_transition_and_instruction_order(self) -> None:
        model = method(graph(LINEAR), (instruction("i1", "t1"), instruction("i2", "t1"), instruction("i3", "t2")))
        override = StepOrderOverride("doc", "method", (TransitionOrder("t2", ("i3",)), TransitionOrder("t1", ("i2", "i1"))))
        plan = PnmlOrderResolver().resolve(model, override)
        self.assertIs(plan.source, StepOrderSource.YAML)
        self.assertEqual([step.instruction_id for step in plan.steps], ["i3", "i2", "i1"])

    def test_override_uuid_mismatch_is_rejected(self) -> None:
        model = method(graph(LINEAR), (instruction("i1", "t1"), instruction("i2", "t2")))
        override = StepOrderOverride("other", "method", (TransitionOrder("t1", ("i1",)), TransitionOrder("t2", ("i2",))))
        with self.assertRaises(ConversionError) as caught:
            PnmlOrderResolver().resolve(model, override)
        self.assertIs(caught.exception.code, ErrorCode.ORDER_SOURCE_MISMATCH)

    def test_single_transition_with_several_input_and_output_places_is_not_ambiguous(self) -> None:
        # Real single-step protocols commonly look like this: a measurement
        # step reads a sample *and* a condition, and writes a result *and*
        # the measured sample - all through one transition. That is several
        # resources on one step, not a sequencing choice, so it must resolve
        # without needing a Step order override.
        sem_like = custom_graph(
            place_ids=("sample", "condition", "result", "measured_sample"),
            transition_ids=("measure",),
            arcs=[
                ("sample", "measure"),
                ("condition", "measure"),
                ("measure", "result"),
                ("measure", "measured_sample"),
            ],
        )
        plan = PnmlOrderResolver().resolve(method(sem_like, (instruction("i1", "measure"),)))
        self.assertIs(plan.source, StepOrderSource.PNML)
        self.assertEqual([step.transition_id for step in plan.steps], ["measure"])

    def test_transition_with_two_distinct_next_transitions_is_still_ambiguous(self) -> None:
        # t1 hands off to BOTH t2 (via p1) and t3 (via p2). No single place
        # has more than one distinct transition on either side, so the
        # place-level check alone would miss this - it must still be caught
        # as a genuine fork once the transitions are reduced to a
        # precedence graph.
        forking = custom_graph(
            place_ids=("p0", "p1", "p2"),
            transition_ids=("t1", "t2", "t3"),
            arcs=[("p0", "t1"), ("t1", "p1"), ("p1", "t2"), ("t1", "p2"), ("p2", "t3")],
        )
        with self.assertRaises(ConversionError) as caught:
            PnmlOrderResolver().resolve(
                method(forking, (instruction("i1", "t1"), instruction("i2", "t2"), instruction("i3", "t3")))
            )
        self.assertIs(caught.exception.code, ErrorCode.AMBIGUOUS_STEP_ORDER)

    def test_two_transitions_merging_into_one_via_different_places_is_ambiguous(self) -> None:
        # The mirror image of the fork above: t1 and t2 both feed t3, via
        # different places, with no arc establishing t1-vs-t2 order.
        merging = custom_graph(
            place_ids=("p0", "p1", "p2"),
            transition_ids=("t1", "t2", "t3"),
            arcs=[("p0", "t1"), ("t1", "p1"), ("p1", "t3"), ("p0", "t2"), ("t2", "p2"), ("p2", "t3")],
        )
        with self.assertRaises(ConversionError) as caught:
            PnmlOrderResolver().resolve(
                method(merging, (instruction("i1", "t1"), instruction("i2", "t2"), instruction("i3", "t3")))
            )
        self.assertIs(caught.exception.code, ErrorCode.AMBIGUOUS_STEP_ORDER)

    def test_several_places_bridge_the_same_two_transitions_without_being_ambiguous(self) -> None:
        # t1 hands t2 two separate resources (p1 and p2) rather than one -
        # still a single linear step-to-step handoff, not a fork.
        double_handoff = custom_graph(
            place_ids=("p0", "p1", "p2", "p3"),
            transition_ids=("t1", "t2"),
            arcs=[("p0", "t1"), ("t1", "p1"), ("t1", "p2"), ("p1", "t2"), ("p2", "t2"), ("t2", "p3")],
        )
        plan = PnmlOrderResolver().resolve(method(double_handoff, (instruction("i1", "t1"), instruction("i2", "t2"))))
        self.assertEqual([step.transition_id for step in plan.steps], ["t1", "t2"])
