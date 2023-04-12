from dataclasses import dataclass, field
import typing
from arcaflow_plugin_sdk import validation, plugin


@dataclass
class NetworkScenarioConfig:
    node_interface_name: typing.Dict[str, typing.List[str]] = field(
        default=None,
        metadata={
            "name": "Node Interface Name",
            "description": "Dictionary with node names as key and values as a list of "
            "their test interfaces. "
            "Required if label_selector is not set.",
        },
    )

    label_selector: typing.Annotated[
        typing.Optional[str], validation.required_if_not("node_interface_name")
    ] = field(
        default=None,
        metadata={
            "name": "Label selector",
            "description": "Kubernetes label selector for the target nodes. "
            "Required if node_interface_name is not set.\n"
            "See https://kubernetes.io/docs/concepts/overview/working-with-objects/labels/ "  # noqa
            "for details.",
        },
    )

    test_duration: typing.Annotated[
        typing.Optional[int], validation.min(1)
    ] = field(
        default=120,
        metadata={
            "name": "Test duration",
            "description": "Duration for which each step of the ingress chaos testing "
            "is to be performed.",
        },
    )

    wait_duration: typing.Annotated[
        typing.Optional[int], validation.min(1)
    ] = field(
        default=300,
        metadata={
            "name": "Wait Duration",
            "description": "Wait duration for finishing a test and its cleanup."
            "Ensure that it is significantly greater than wait_duration",
        },
    )

    instance_count: typing.Annotated[
        typing.Optional[int], validation.min(1)
    ] = field(
        default=1,
        metadata={
            "name": "Instance Count",
            "description": "Number of nodes to perform action/select that match "
            "the label selector.",
        },
    )

    execution_type: typing.Optional[str] = field(
        default="parallel",
        metadata={
            "name": "Execution Type",
            "description": "The order in which the ingress filters are applied. "
            "Execution type can be 'serial' or 'parallel'",
        },
    )

    network_params: typing.Dict[str, str] = field(
        default=None,
        metadata={
            "name": "Network Parameters",
            "description": "The network filters that are applied on the interface. "
            "The currently supported filters are latency, "
            "loss and bandwidth",
        },
    )

    cerberus_enabled: typing.Optional[bool] = field(
        default=False,
        metadata={
            "name": "Cerberus Enabled",
            "description": "if Cerberus is enabled, the plugin status will be pushed to Cerberus",
        },
    )

    cerberus_url: typing.Optional[str] = field(
        default=False,
        metadata={
            "name": "Cerberus Url",
            "description": "Cerberus Endpoint URL",
        },
    )

    cerberus_check_application_routes: typing.Optional[bool] = field(
        default=False,
        metadata={
            "name": "Cerberus Check Application Routes",
            "description": "Cerberus Check Application Routes",
        },
    )

    krkn_exit_on_failure: typing.Optional[bool] = field(
        default=False,
        metadata={
            "name": "Exit On Failure",
            "description": "On failure Exit(1)",
        },
    )

    j2_tpl_job: typing.Optional[str] = field(
        default="",
        metadata={
            "name": "Job Template",
            "description": "Jinja2 Job template",
        },
    )

    j2_tpl_pod_interface: typing.Optional[str] = field(
        default="",
        metadata={
            "name": "Pod interface template",
            "description": "Jinja2 pod interface template",
        },
    )
    j2_tpl_pod_module: typing.Optional[str] = field(
        default="",
        metadata={
            "name": "Pod module template",
            "description": "Jinja2 pod module template",
        },
    )


@dataclass
class NetworkScenarioSuccessOutput:
    filter_direction: str = field(
        metadata={
            "name": "Filter Direction",
            "description": "Direction in which the traffic control filters are applied "
            "on the test interfaces",
        }
    )

    test_interfaces: typing.Dict[str, typing.List[str]] = field(
        metadata={
            "name": "Test Interfaces",
            "description": "Dictionary of nodes and their interfaces on which "
            "the chaos experiment was performed",
        }
    )

    network_parameters: typing.Dict[str, str] = field(
        metadata={
            "name": "Network Parameters",
            "description": "The network filters that are applied on the interfaces",
        }
    )

    execution_type: str = field(
        metadata={
            "name": "Execution Type",
            "description": "The order in which the filters are applied",
        }
    )


@dataclass
class NetworkScenarioErrorOutput:
    error: str = field(
        metadata={
            "name": "Error",
            "description": "Error message when there is a run-time error during "
            "the execution of the scenario",
        }
    )
