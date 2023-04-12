import krkn_lib_kubernetes_draft
import yaml
import time
import re
import sys
import logging
import typing
import krkn_lib_kubernetes_draft as krkn_lib_kubernetes
from schema import (
    NetworkScenarioConfig,
    NetworkScenarioErrorOutput,
    NetworkScenarioSuccessOutput,
)
from cerberus import Cerberus
from traceback import format_exc
from jinja2 import Environment, BaseLoader
from arcaflow_plugin_sdk import plugin


def get_default_interface(
    lib_k8s: krkn_lib_kubernetes.KrknLibKubernetes,
    node: str,
    pod_template,
) -> str:
    """
    Function that returns a random interface from a node

    Args:
        lib_k8s (krkn_lib_kubernetes.KrknLibKubernetes)
            - Kraken kubernetes library

        node (string)
            - Node from which the interface is to be returned

        pod_template (jinja2.environment.Template)
            - The YAML template used to instantiate a pod to query
              the node's interface


    Returns:
        Default interface (string) belonging to the node
    """

    pod_body = yaml.safe_load(pod_template.render(nodename=node))
    logging.info("Creating pod to query interface on node %s", node)
    lib_k8s.create_pod(pod_body, "default", 300)

    try:
        cmd = ["ip", "r"]
        output = lib_k8s.exec_cmd_in_pod(cmd, "fedtools", "default")

        if not output:
            logging.error("Exception occurred while executing command in pod")
            # TODO check exit 1 equivalent strategy
            sys.exit(1)

        routes = output.split("\n")
        for route in routes:
            if "default" in route:
                default_route = route
                break

        interfaces = [default_route.split()[4]]

    finally:
        logging.info("Deleting pod to query interface on node")
        lib_k8s.delete_pod("fedtools", "default")
    # TODO: is returning a list instead of a string this might be a bug
    return interfaces


def verify_interface(
    lib_k8s: krkn_lib_kubernetes.KrknLibKubernetes,
    input_interface_list: typing.List[str],
    node: str,
    pod_template,
) -> typing.List[str]:
    """
    Function that verifies whether a list of interfaces is present in the node.
    If the list is empty, it fetches the interface of the default route

    Args:
        lib_k8s (krkn_lib_kubernetes.KrknLibKubernetes)
            - Kraken kubernetes library

        input_interface_list (List of strings)
            - The interfaces to be checked on the node

        node (string):
            - Node on which input_interface_list is to be verified

        pod_template (jinja2.environment.Template)
            - The YAML template used to instantiate a pod to query
              the node's interfaces

    Returns:
        The interface list for the node
    """
    pod_body = yaml.safe_load(pod_template.render(nodename=node))
    logging.info(f"Creating pod to query interface on node {node}")
    lib_k8s.create_pod(pod_body, "default", 300)
    try:
        if not input_interface_list:
            cmd = ["ip", "r"]
            output = lib_k8s.exec_cmd_in_pod(cmd, "fedtools", "default")

            if not output:
                logging.error(
                    "Exception occurred while executing command in pod"
                )
                # TODO check exit 1 equivalent strategy
                sys.exit(1)

            routes = output.split("\n")
            for route in routes:
                if "default" in route:
                    default_route = route
                    break

            input_interface_list = [default_route.split()[4]]

        else:
            cmd = ["ip", "-br", "addr", "show"]
            output = lib_k8s.exec_cmd_in_pod(cmd, "fedtools", "default")

            if not output:
                logging.error(
                    "Exception occurred while executing command in pod"
                )
                # TODO: is sys.exit(1) correct in a container context?
                # TODO check exit 1 equivalent strategy
                sys.exit(1)

            interface_ip = output.split("\n")
            node_interface_list = [
                interface.split()[0] for interface in interface_ip[:-1]
            ]

            for interface in input_interface_list:
                if interface not in node_interface_list:
                    logging.error(
                        "Interface %s not found in node %s interface list %s"
                        % (interface, node, node_interface_list)
                    )
                    raise Exception(
                        "Interface %s not found in node %s interface list %s"
                        % (interface, node, node_interface_list)
                    )
    finally:
        logging.info("Deleteing pod to query interface on node")
        lib_k8s.delete_pod("fedtools", "default")

    return input_interface_list


def get_node_interfaces(
    lib_k8s: krkn_lib_kubernetes.KrknLibKubernetes,
    node_interface_dict: typing.Dict[str, typing.List[str]],
    label_selector: str,
    instance_count: int,
    pod_template,
) -> typing.Dict[str, typing.List[str]]:
    """
    Function that is used to process the input dictionary with the nodes and
    its test interfaces.

    If the dictionary is empty, the label selector is used to select the nodes,
    and then a random interface on each node is chosen as a test interface.

    If the dictionary is not empty, it is filtered to include the nodes which
    are active and then their interfaces are verified to be present

    Args:
        lib_k8s (krkn_lib_kubernetes.KrknLibKubernetes)
            - Kraken kubernetes library

        node_interface_dict (Dictionary with keys as node name and value as
        a list of interface names)
            - Nodes and their interfaces for the scenario

        label_selector (string):
            - Label selector to get nodes if node_interface_dict is empty

        instance_count (int):
            - Number of nodes to fetch in case node_interface_dict is empty

        pod_template (jinja2.environment.Template)
            - The YAML template used to instantiate a pod to query
              the node's interfaces


    Returns:
        Filtered dictionary containing the test nodes and their test interfaces
    """
    if not node_interface_dict:
        if not label_selector:
            raise Exception(
                "If node names and interfaces aren't provided, "
                "then the label selector must be provided"
            )
        nodes = lib_k8s.get_node(None, label_selector, instance_count)
        node_interface_dict = {}
        for node in nodes:
            node_interface_dict[node] = get_default_interface(
                lib_k8s, node, pod_template
            )
    else:
        node_name_list = node_interface_dict.keys()
        filtered_node_list = []

        for node in node_name_list:
            filtered_node_list.extend(
                lib_k8s.get_node(node, label_selector, instance_count)
            )

        for node in filtered_node_list:
            node_interface_dict[node] = verify_interface(
                lib_k8s, node_interface_dict[node], node, pod_template
            )

    return node_interface_dict


def apply_ingress_filter(
    lib_k8s: krkn_lib_kubernetes.KrknLibKubernetes,
    cfg: NetworkScenarioConfig,
    interface_list: typing.List[str],
    node: str,
    pod_template,
    job_template,
    create_interfaces: bool = True,
    param_selector: str = "all",
) -> str:
    """
    Function that applies the filters to shape incoming traffic to
    the provided node's interfaces.
    This is done by adding a virtual interface before each physical interface
    and then performing egress traffic control on the virtual interface

    Args:
        lib_k8s (krkn_lib_kubernetes.KrknLibKubernetes)
            - Kraken kubernetes library
        cfg (NetworkScenarioConfig)
            - Configurations used in this scenario

        interface_list (List of strings)
            - The interfaces on the node on which the filter is applied

        node (string):
            - Node on which the interfaces in interface_list are present

        pod_template (jinja2.environment.Template))
            - The YAML template used to instantiate a pod to create
              virtual interfaces on the node

        job_template (jinja2.environment.Template))
            - The YAML template used to instantiate a job to apply and remove
              the filters on the interfaces

        create_interfaces (bool)
            - Create interfaces on pod

        param_selector (string)
            - Used to specify what kind of filter to apply. Useful during
              serial execution mode. Default value is 'all'

    Returns:
        The name of the job created that executes the commands on a node
        for ingress chaos scenario
    """

    network_params = cfg.network_params
    if param_selector != "all":
        network_params = {param_selector: cfg.network_params[param_selector]}

    if create_interfaces:
        create_virtual_interfaces(lib_k8s, interface_list, node, pod_template)

    exec_cmd = get_ingress_cmd(
        interface_list, network_params, duration=cfg.test_duration
    )
    logging.info("Executing %s on node %s", exec_cmd, node)
    job_body = yaml.safe_load(
        job_template.render(
            jobname=str(hash(node))[:5], nodename=node, cmd=exec_cmd
        )
    )
    api_response = lib_k8s.create_job(job_body)

    if api_response is None:
        raise Exception("Error creating job")

    return job_body["metadata"]["name"]


def create_virtual_interfaces(
    lib_k8s: krkn_lib_kubernetes.KrknLibKubernetes,
    interface_list: typing.List[str],
    node: str,
    pod_template,
) -> None:
    """
    Function that creates a privileged pod and uses it to create
    virtual interfaces on the node

    Args:
        lib_k8s (krkn_lib_kubernetes_draft.KrknLibKubernetes)
            - Kraken kubernetes library

        interface_list (List of strings)
            - The list of interfaces on the node for which virtual interfaces
              are to be created

        node (string)
            - The node on which the virtual interfaces are created

        pod_template (jinja2.environment.Template))
            - The YAML template used to instantiate a pod to create
              virtual interfaces on the node
    """
    pod_body = yaml.safe_load(pod_template.render(nodename=node))
    lib_k8s.create_pod(pod_body, "default", 300)
    logging.info(
        "Creating %s virtual interfaces on node %s using a pod",
        str(len(interface_list)),
        node,
    )
    create_ifb(lib_k8s, len(interface_list), "modtools")
    logging.info("Deleting pod used to create virtual interfaces")
    lib_k8s.delete_pod("modtools", "default")


def delete_virtual_interfaces(
    lib_k8s: krkn_lib_kubernetes.KrknLibKubernetes,
    node_list: typing.List[str],
    pod_template,
):
    """
    Function that creates a privileged pod and uses it to delete all
    virtual interfaces on the specified nodes

    Args:
        lib_k8s (krkn_lib_kubernetes_draft.KrknLibKubernetes)
            - Kraken kubernetes library

        node_list (List of strings)
            - The list of nodes on which the list of virtual interfaces are
              to be deleted

        node (string)
            - The node on which the virtual interfaces are created

        pod_template (jinja2.environment.Template))
            - The YAML template used to instantiate a pod to delete
              virtual interfaces on the node
    """

    for node in node_list:
        pod_body = yaml.safe_load(pod_template.render(nodename=node))
        lib_k8s.create_pod(pod_body, "default", 300)
        logging.info("Deleting all virtual interfaces on node %s", node)
        delete_ifb(lib_k8s, "modtools")
        lib_k8s.delete_pod("modtools", "default")


def create_ifb(
    lib_k8s: krkn_lib_kubernetes.KrknLibKubernetes, number: int, pod_name: str
):
    """
    Function that creates virtual interfaces in a pod.
    Makes use of modprobe commands
    """

    exec_command = [
        "chroot",
        "/host",
        "modprobe",
        "ifb",
        "numifbs=" + str(number),
    ]
    lib_k8s.exec_cmd_in_pod(exec_command, pod_name, "default")

    for i in range(0, number):
        exec_command = ["chroot", "/host", "ip", "link", "set", "dev"]
        exec_command += ["ifb" + str(i), "up"]
        lib_k8s.exec_cmd_in_pod(exec_command, pod_name, "default")


def delete_ifb(lib_k8s: krkn_lib_kubernetes.KrknLibKubernetes, pod_name: str):
    """
    Function that deletes all virtual interfaces in a pod.
    Makes use of modprobe command
    """

    exec_command = ["chroot", "/host", "modprobe", "-r", "ifb"]
    lib_k8s.exec_cmd_in_pod(exec_command, pod_name, "default")


def get_job_pods(lib_k8s: krkn_lib_kubernetes.KrknLibKubernetes, api_response):
    """
    Function that gets the pod corresponding to the job

    Args:
        cli (CoreV1Api)
            - Object to interact with Kubernetes Python client's CoreV1 API

        api_response
            - The API response for the job status

    Returns
        Pod corresponding to the job
    """

    controllerUid = api_response.metadata.labels["controller-uid"]
    pod_label_selector = "controller-uid=" + controllerUid
    pods_list = lib_k8s.list_pods(
        label_selector=pod_label_selector, namespace="default"
    )

    return pods_list[0]


def wait_for_job(
    lib_k8s: krkn_lib_kubernetes.KrknLibKubernetes,
    job_list: typing.List[str],
    timeout: int = 300,
) -> None:
    """
    Function that waits for a list of jobs to finish within a time period

    Args:
        lib_k8s (krkn_lib_kubernetes.KrknLibKubernetes)
            - Kraken kubernetes library

        job_list (List of strings)
            - The list of jobs to check for completion

        timeout (int)
            - Max duration to wait for checking whether the jobs are completed
    """

    wait_time = time.time() + timeout
    count = 0
    job_len = len(job_list)
    while count != job_len:
        for job_name in job_list:
            try:
                api_response = lib_k8s.get_job_status(
                    job_name, namespace="default"
                )
                if (
                    api_response.status.succeeded is not None
                    or api_response.status.failed is not None
                ):
                    count += 1
                    job_list.remove(job_name)
            except Exception:
                logging.warning("Exception in getting job status")
            if time.time() > wait_time:
                raise Exception(
                    "Jobs did not complete within "
                    "the {0}s timeout period".format(timeout)
                )
            time.sleep(5)


def delete_jobs(
    lib_k8s: krkn_lib_kubernetes.KrknLibKubernetes,
    job_list: typing.List[str],
):
    """
    Function that deletes jobs

    Args:
        lib_k8s (krkn_lib_kubernetes.KrknLibKubernetes)
            - Kraken kubernetes library

        job_list (List of strings)
            - The list of jobs to delete
    """

    for job_name in job_list:
        try:
            api_response = lib_k8s.get_job_status(
                job_name, namespace="default"
            )
            if api_response.status.failed is not None:
                pod_name = get_job_pods(lib_k8s, api_response)
                pod_stat = lib_k8s.read_pod(name=pod_name, namespace="default")
                logging.error(pod_stat.status.container_statuses)
                # TODO review the get_pod_log output
                #  (maybe it's not string even if the doc says that)
                pod_log_response = lib_k8s.get_pod_log(
                    name=pod_name, namespace="default"
                )
                # pod_log = pod_log_response.data.decode("utf-8")
                logging.error(pod_log_response)
        except Exception as e:
            logging.warning("Exception in getting job status: %s", str(e))
        lib_k8s.delete_job(name=job_name, namespace="default")


def get_ingress_cmd(
    interface_list: typing.List[str],
    network_parameters: typing.Dict[str, str],
    duration: int = 300,
):
    """
    Function that returns the commands to the ingress traffic shaping on
    the node.
    First, the virtual interfaces created are linked to the test interfaces
    such that there is a one-to-one mapping between a virtual interface and
    a test interface.
    Then, incoming  traffic to each test interface is forced to first pass
    through the corresponding virtual interface.
    Linux's tc commands are then used to performing egress traffic control
    on the virtual interface. Since the outbound traffic from
    the virtual interface passes through the test interface, this is
    effectively ingress traffic control.
    After a certain time interval, the traffic is restored to normal

    Args:
        interface_list (List of strings)
            - Test interface list

        network_parameters (Dictionary with key and value as string)
            - Loss/Delay/Bandwidth and their corresponding values

        duration (int)
            - Duration for which the traffic control is to be done

    Returns:
        The traffic shaping commands as a string
    """

    tc_set = tc_unset = tc_ls = ""
    param_map = {"latency": "delay", "loss": "loss", "bandwidth": "rate"}

    interface_pattern = re.compile(r"^[a-z0-9\-\@\_]+$")
    ifb_pattern = re.compile(r"^ifb[0-9]+$")

    for i, interface in enumerate(interface_list):
        if not interface_pattern.match(interface):
            logging.error(
                "Interface name can only consist of alphanumeric characters"
            )
            raise Exception(
                "Interface '{0}' does not match the required regex pattern :"
                r" ^[a-z0-9\-\@\_]+$".format(interface)
            )

        ifb_name = "ifb{0}".format(i)
        if not ifb_pattern.match(ifb_name):
            logging.error("Invalid IFB name")
            raise Exception(
                "Interface '{0}' is an invalid IFB name. IFB name should "
                "follow the regex pattern ^ifb[0-9]+$".format(ifb_name)
            )

        tc_set += "tc qdisc add dev {0} handle ffff: ingress;".format(
            interface
        )
        tc_set += "tc filter add dev {0} parent ffff: protocol ip u32 match u32 0 0 action mirred egress redirect dev {1};".format(  # noqa
            interface, ifb_name
        )
        tc_set = "{0} tc qdisc add dev {1} root netem".format(tc_set, ifb_name)
        tc_unset = "{0} tc qdisc del dev {1} root ;".format(tc_unset, ifb_name)
        tc_unset += "tc qdisc del dev {0} handle ffff: ingress;".format(
            interface
        )
        tc_ls = "{0} tc qdisc ls dev {1} ;".format(tc_ls, ifb_name)

        for parameter in network_parameters.keys():
            tc_set += " {0} {1} ".format(
                param_map[parameter], network_parameters[parameter]
            )
        tc_set += ";"

    exec_cmd = "{0} {1} sleep {2};{3} sleep 20;{4}".format(
        tc_set, tc_ls, duration, tc_unset, tc_ls
    )

    return exec_cmd


@plugin.step(
    id="network_chaos",
    name="Network Ingress",
    description="Applies filters to ihe ingress side of node(s) interfaces",
    outputs={
        "success": NetworkScenarioSuccessOutput,
        "error": NetworkScenarioErrorOutput,
    },
)
def network_chaos(
    cfg: NetworkScenarioConfig,
) -> typing.Tuple[
    str, typing.Union[NetworkScenarioSuccessOutput, NetworkScenarioErrorOutput]
]:
    """
    Function that performs the ingress network chaos scenario based
    on the provided configuration

    Args:
        cfg (NetworkScenarioConfig)
            - The object containing the configuration for the scenario

    Returns
        A 'success' or 'error' message along with their details
    """
    base_loader = BaseLoader()
    cerberus = Cerberus(
        cfg.krkn_exit_on_failure,
        cfg.cerberus_enabled,
        cfg.cerberus_url,
        cfg.cerberus_check_application_routes,
    )
    env = Environment(loader=base_loader)
    # TODO: load in container env the variables to be replaced in templates
    job_template = env.from_string(cfg.j2_tpl_job)
    pod_interface_template = env.from_string(cfg.j2_tpl_pod_interface)
    pod_module_template = env.from_string(cfg.j2_tpl_pod_module)

    lib_k8s = krkn_lib_kubernetes.KrknLibKubernetes(
        kubeconfig_string=cfg.kubeconfig
    )

    try:
        node_interface_dict = get_node_interfaces(
            lib_k8s,
            cfg.node_interface_name,
            cfg.label_selector,
            cfg.instance_count,
            pod_interface_template,
        )
    except Exception:
        return "error", NetworkScenarioErrorOutput(format_exc())

    job_list = []
    failed_post_scenarios = ""
    publish = True

    try:
        if cfg.execution_type == "parallel":
            for node in node_interface_dict:
                job_list.append(
                    apply_ingress_filter(
                        lib_k8s,
                        cfg,
                        node_interface_dict[node],
                        node,
                        pod_module_template,
                        job_template,
                    )
                )
            logging.info("Waiting for parallel job to finish")
            start_time = int(time.time())
            wait_for_job(lib_k8s, job_list[:], cfg.wait_duration)
            end_time = int(time.time())
            if publish:
                # TODO: define the publish_kraken_status on cerberus
                cerberus.publish_kraken_status(
                    failed_post_scenarios,
                    start_time,
                    end_time,
                )

        elif cfg.execution_type == "serial":
            create_interfaces = True
            for param in cfg.network_params:
                for node in node_interface_dict:
                    job_list.append(
                        apply_ingress_filter(
                            lib_k8s,
                            cfg,
                            node_interface_dict[node],
                            node,
                            pod_module_template,
                            job_template,
                            create_interfaces,
                            param,
                        )
                    )
                logging.info("Waiting for serial job to finish")
                start_time = int(time.time())
                wait_for_job(
                    lib_k8s,
                    job_list[:],
                    cfg.wait_duration,
                )
                logging.info("Deleting jobs")
                delete_jobs(
                    lib_k8s,
                    job_list[:],
                )
                job_list = []
                logging.info(
                    "Waiting for wait_duration : %s", str(cfg.wait_duration)
                )
                time.sleep(cfg.wait_duration)
                end_time = int(time.time())
                if publish:
                    # TODO
                    cerberus.publish_kraken_status(
                        failed_post_scenarios,
                        start_time,
                        end_time,
                    )
                create_interfaces = False
        else:
            return "error", NetworkScenarioErrorOutput(
                "Invalid execution type - serial and parallel are "
                "the only accepted types"
            )
        return "success", NetworkScenarioSuccessOutput(
            filter_direction="ingress",
            test_interfaces=node_interface_dict,
            network_parameters=cfg.network_params,
            execution_type=cfg.execution_type,
        )
    except Exception as e:
        logging.error("Network Chaos exiting due to Exception - %s", str(e))
        return "error", NetworkScenarioErrorOutput(format_exc())
    finally:
        delete_virtual_interfaces(
            lib_k8s,
            list(node_interface_dict.keys()),
            pod_module_template,
        )
        logging.info("Deleting jobs(if any)")
        delete_jobs(lib_k8s, job_list[:])
