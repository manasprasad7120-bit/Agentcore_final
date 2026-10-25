from typing import Any

from loguru import logger

from agentcore.custom.custom_node.node import Node
from agentcore.inputs.inputs import HandleInput, IntInput
from agentcore.schema.data import Data
from agentcore.schema.dataframe import DataFrame
from agentcore.template.field.base import Output

DEFAULT_MAX_LOOP_ITERATIONS = 100


class Loop(Node):
    display_name = "Loop"
    description = (
        "Iterates over a list of Data objects, outputting one item at a time and aggregating results from loop inputs."
    )
    icon = "infinity"

    inputs = [
        HandleInput(
            name="data",
            display_name="Inputs",
            info="The initial list of Data objects or DataFrame to iterate over.",
            input_types=["DataFrame"],
        ),
        IntInput(
            name="max_iterations",
            display_name="Max Iterations",
            info=(
                "Hard cap on loop iterations. Forces the loop to stop after this many "
                "iterations even if the input data is longer — protects against runaway cycles."
            ),
            value=DEFAULT_MAX_LOOP_ITERATIONS,
            advanced=True,
        ),
    ]

    outputs = [
        Output(display_name="Item", name="item", method="item_output", allows_loop=True, group_outputs=True),
        Output(display_name="Done", name="done", method="done_output", group_outputs=True),
    ]

    def initialize_data(self) -> None:
        """Initialize the data list, context index, and aggregated list."""
        if self.ctx.get(f"{self._id}_initialized", False):
            return

        data_list = self._validate_data(self.data)

        self.update_ctx(
            {
                f"{self._id}_data": data_list,
                f"{self._id}_index": 0,
                f"{self._id}_aggregated": [],
                f"{self._id}_initialized": True,
            }
        )

    def _validate_data(self, data):
        """Validate and return a list of Data objects."""
        if isinstance(data, DataFrame):
            return data.to_data_list()
        if isinstance(data, Data):
            return [data]
        if isinstance(data, list) and all(isinstance(item, Data) for item in data):
            return data
        msg = "The 'data' input must be a DataFrame, a list of Data objects, or a single Data object."
        raise TypeError(msg)

    def evaluate_stop_loop(self) -> bool:
        """Evaluate whether to stop item or done output."""
        current_index = self.ctx.get(f"{self._id}_index", 0)
        data_length = len(self.ctx.get(f"{self._id}_data", []))
        # Hard cap: read user-configured Max Iterations from the component input,
        # falling back to the default if unset/invalid.
        max_iter = getattr(self, "max_iterations", None) or DEFAULT_MAX_LOOP_ITERATIONS
        try:
            max_iter = int(max_iter)
        except (TypeError, ValueError):
            max_iter = DEFAULT_MAX_LOOP_ITERATIONS
        if max_iter <= 0:
            max_iter = DEFAULT_MAX_LOOP_ITERATIONS
        if current_index > max_iter:
            logger.warning(
                f"[Loop {self._id}] hit Max Iterations cap ({max_iter}) — forcing stop."
            )
            return True
        return current_index > data_length

    def _build_summary_data(self) -> Data:
        """Build a Data summary of the loop run for the Component Output inspector."""
        aggregated = self.ctx.get(f"{self._id}_aggregated", [])
        data_list = self.ctx.get(f"{self._id}_data", [])

        aggregated_view: list[Any] = []
        for entry in aggregated:
            if isinstance(entry, Data):
                aggregated_view.append(entry.data)
            elif hasattr(entry, "text"):
                aggregated_view.append({"text": getattr(entry, "text", "")})
            else:
                aggregated_view.append(entry)

        source_view: list[Any] = []
        for entry in data_list:
            if isinstance(entry, Data):
                source_view.append(entry.data)
            else:
                source_view.append(str(entry))

        return Data(
            data={
                "text": (
                    f"Loop complete — iterated {len(data_list)} item(s), "
                    f"aggregated {len(aggregated)} result(s)."
                ),
                "iterations": len(data_list),
                "aggregated_count": len(aggregated),
                "source_items": source_view,
                "aggregated_results": aggregated_view,
            }
        )

    def item_output(self) -> Data:
        """Output the next item in the list or stop if done."""
        self.initialize_data()
        current_item = Data(text="")

        if self.evaluate_stop_loop():
            # Activate the Done branch and inactivate Item so the router exits the cycle.
            self.stop("item")
            self.start("done")
            current_item = self._build_summary_data()
        else:
            # Keep the 'done' branch inactive while still iterating so the router
            # picks the 'item' (body) successor instead of exiting the cycle.
            self.stop("done")
            self.start("item")
            data_list, current_index = self.loop_variables()
            if current_index < len(data_list):
                try:
                    current_item = data_list[current_index]
                except IndexError:
                    current_item = Data(text="")
            self.aggregated_output()
            self.update_ctx({f"{self._id}_index": current_index + 1})

            # If we just consumed the last source item, surface the summary on the
            # 'item' output so the inspector shows useful info (item_output's `stop`
            # branch never runs because done_output detects stop first and routes
            # to Done).
            if current_index >= len(data_list):
                current_item = self._build_summary_data()

        self.update_dependency()
        return current_item

    def update_dependency(self):
        item_dependency_id = self.get_incoming_edge_by_target_param("item")
        if item_dependency_id not in self.graph.run_manager.run_predecessors[self._id]:
            self.graph.run_manager.run_predecessors[self._id].append(item_dependency_id)

    def done_output(self) -> DataFrame:
        """Trigger the done output when iteration is complete."""
        self.initialize_data()

        if self.evaluate_stop_loop():
            self.stop("item")
            self.start("done")
            aggregated = self.ctx.get(f"{self._id}_aggregated", [])
            return DataFrame(aggregated)
        self.stop("done")
        return DataFrame([])

    def loop_variables(self):
        """Retrieve loop variables from context."""
        return (
            self.ctx.get(f"{self._id}_data", []),
            self.ctx.get(f"{self._id}_index", 0),
        )

    def _read_loop_back_value(self):
        """Read the actual runtime value from the upstream vertex wired into the loop-back (∞) handle.

        ``self.item`` resolves to the static Output declaration (because ``item`` is declared as
        an Output, not an Input on this component). We find the upstream vertex by inspecting
        the graph's edges, then read its value from the LangGraph state — extracting the
        specific output the edge connects to so multi-output upstreams (e.g. Parser with
        Parsed Text + Parsed Data) yield the correct value, not the whole dict.
        """
        graph = getattr(self, "graph", None)
        if graph is None:
            return None

        cycle_verts: set = set()
        try:
            state = getattr(graph, "_current_lg_state", None)
            if state is not None:
                cycle_verts = set(state.get("cycle_vertices", []) or [])
        except Exception:
            cycle_verts = set()

        # Find the upstream vertex_id AND the source-handle name of the loop-back edge.
        # The loop-back is the edge targeting Loop whose source is in the same cycle.
        upstream_id = None
        upstream_source_name = None
        try:
            for edge in getattr(graph, "edges", []):
                if edge.get("target") != self._id:
                    continue
                src = edge.get("source")
                target_handle = edge.get("data", {}).get("targetHandle", {})
                source_handle = edge.get("data", {}).get("sourceHandle", {})
                field_name = target_handle.get("fieldName") if isinstance(target_handle, dict) else None
                source_name = source_handle.get("name") if isinstance(source_handle, dict) else None
                if src and src in cycle_verts and src != self._id:
                    upstream_id = src
                    upstream_source_name = source_name
                    break
                if field_name == "item" and not upstream_id:
                    upstream_id = src
                    upstream_source_name = source_name
        except Exception:
            logger.opt(exception=True).debug(f"[Loop {self._id}] error scanning edges for loop-back source")
            return None

        if not upstream_id:
            return None

        # Prefer the LangGraph state snapshot.
        state = getattr(graph, "_current_lg_state", None)
        value = None
        if state is not None:
            vertices_results = state.get("vertices_results") or {}
            value = vertices_results.get(upstream_id)

        # Fallback: read from the vertex object directly.
        if value is None and hasattr(graph, "get_vertex"):
            upstream = graph.get_vertex(upstream_id)
            if upstream is not None:
                value = getattr(upstream, "built_result", None)

        # Multi-output upstream returns a dict {output_name: value}. Extract the
        # specific output this edge connects to.
        if isinstance(value, dict):
            if upstream_source_name and upstream_source_name in value:
                value = value[upstream_source_name]
            elif len(value) == 1:
                value = next(iter(value.values()))

        return value

    def aggregated_output(self) -> list[Data]:
        """Append the upstream loop-back value to the aggregated list."""
        self.initialize_data()

        data_list = self.ctx.get(f"{self._id}_data", [])
        aggregated = self.ctx.get(f"{self._id}_aggregated", [])
        loop_input = self._read_loop_back_value()
        if loop_input is not None and not isinstance(loop_input, str) and len(aggregated) <= len(data_list):
            aggregated.append(loop_input)
            self.update_ctx({f"{self._id}_aggregated": aggregated})
        return aggregated
