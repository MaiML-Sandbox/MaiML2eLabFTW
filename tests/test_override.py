from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from maiml2elabftw.core.errors import ConversionError, ErrorCode
from maiml2elabftw.ordering import load_step_order_override


class OverrideLoaderTests(unittest.TestCase):
    def test_loads_version_one_yaml(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "order.yaml"
            path.write_text(
                """version: 1
source:
  document_uuid: doc
  method_uuid: method
steps:
  - transition_id: t1
    instruction_ids: [i1]
""",
                encoding="utf-8",
            )
            result = load_step_order_override(path)
        self.assertEqual(result.document_uuid, "doc")
        self.assertEqual(result.steps[0].instruction_ids, ("i1",))

    def test_rejects_empty_instruction_list(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "order.yaml"
            path.write_text(
                "version: 1\nsource: {document_uuid: doc, method_uuid: method}\nsteps: [{transition_id: t1, instruction_ids: []}]\n",
                encoding="utf-8",
            )
            with self.assertRaises(ConversionError) as caught:
                load_step_order_override(path)
        self.assertIs(caught.exception.code, ErrorCode.INVALID_ORDER_FILE)

