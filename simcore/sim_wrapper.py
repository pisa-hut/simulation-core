import contextlib
import logging
import time

import grpc
from google.protobuf.struct_pb2 import Struct
from pisa_api import (
    config_pb2,
    control_pb2,
    empty_pb2,
    path_pb2,
    scenario_pb2,
    sim_server_pb2,
    sim_server_pb2_grpc,
)

from simcore.utils.control import Ctrl
from simcore.utils.sps import ScenarioPack
from simcore.utils.util import get_cfg

logger = logging.getLogger(__name__)


class SimWrapper:
    def __init__(self, sim_spec: dict, dt_ns: int | None = None):
        self._sim_spec = sim_spec

        if dt_ns is None:
            logger.warning("dt not specified for SimWrapper, defaulting to 0.01s")
            self._dt_s = 0.01
        else:
            self._dt_s = dt_ns / 1e9

        self._url = self._sim_spec.get("url", "localhost:50053")
        self._timeout = float(self._sim_spec.get("timeout", 100.0))
        self._sim_cfg_path = self._sim_spec.get("config_path", None)
        self._sim_output_dir = self._sim_spec.get("output_path", "/mnt/output")

        if self._sim_cfg_path is not None:
            self._sim_cfg = get_cfg(self._sim_cfg_path)
        else:
            self._sim_cfg = None

        # long-lived channel
        self._channel = grpc.insecure_channel(self._url)
        self._stub = sim_server_pb2_grpc.SimServerStub(self._channel)
        while True:
            try:
                pong = self._stub.Ping(empty_pb2.Empty(), timeout=self._timeout)
                logger.info(f"Simulator ping response: {pong.msg}")
                break
            except Exception:
                logger.warning("Simulator ping failed, retrying...")
                time.sleep(2)
        logger.info("Simulator service is alive")
        self._connected = True

        self.init()

    # ---------------------------
    # Public API
    # ---------------------------

    def init(self):
        cfg_struct = Struct()
        cfg_struct.update(self._sim_cfg if self._sim_cfg is not None else {})
        config = config_pb2.Config(config=cfg_struct)
        scenario_spec = self._sim_spec.get("scenario", None)
        request = sim_server_pb2.SimServerMessages.InitRequest(
            config=config,
            output_dir=path_pb2.Path(path=str(self._sim_output_dir)),
            dt=self._dt_s,
            scenario=scenario_pb2.Scenario(
                format=scenario_spec.get("format"),
                name=scenario_spec.get("name"),
                path=path_pb2.Path(path=scenario_spec.get("path")),
            ),
        )
        response = self._stub.Init(request, timeout=self._timeout)
        logger.info(f"Init response: {response.msg}")
        if not response.success:
            raise RuntimeError(f"Server Init returned success=false: {response.msg}")

    def reset(
        self,
        output_dir: str,
        scenario_pack: ScenarioPack,
        params: dict[str, str] | None = None,
    ):
        self._ensure_ready()
        req = sim_server_pb2.SimServerMessages.ResetRequest(
            output_dir=path_pb2.Path(path=str(output_dir)),
            scenario_pack=scenario_pack.to_protobuf(),
            params=params or {},
        )
        try:
            resp = self._stub.Reset(req, timeout=self._timeout)
            return resp.objects
        except grpc.RpcError as e:
            raise RuntimeError(f"SimWrapper Reset failed: {e.code().name} - {e.details()}") from e

    def step(self, ctrl_cmd: Ctrl, time_stamp_ns: int):
        self._ensure_ready()

        if ctrl_cmd is None:
            return control_pb2.CtrlCmd(mode=control_pb2.CtrlMode.NONE)  # empty CtrlCmd

        # payload = Struct()
        # payload.update(ctrl_cmd.payload)

        # ctrl_pb = control_pb2.CtrlCmd(
        #     mode=control_pb2.CtrlMode.ACKERMANN,  # 根據 Ctrl.mode 決定 CtrlMode
        #     payload=payload,
        # )

        req = sim_server_pb2.SimServerMessages.StepRequest(
            ctrl_cmd=ctrl_cmd, timestamp_ns=int(time_stamp_ns)
        )
        try:
            resp = self._stub.Step(req, timeout=self._timeout)
            # StepResponse { repeated ObjectState objects }
            return resp.objects
        except grpc.RpcError as e:
            raise RuntimeError(f"Step failed: {e.code().name} - {e.details()}") from e

    def stop(self):
        """
        rpc Stop(Empty) returns (Empty)
        """
        if self._stub is None:
            return
        try:
            self._stub.Stop(empty_pb2.Empty(), timeout=min(self._timeout, 5.0))
        except grpc.RpcError as e:
            logger.warning(f"[WARN] Stop failed: {e.code().name} - {e.details()}")
        finally:
            self._connected = False
            self._close()

    def should_quit(self) -> bool:
        """
        rpc ShouldQuit(Empty) returns (ShouldQuitResponse)
        """
        if self._stub is None or not self._connected:
            return True
        try:
            resp = self._stub.ShouldQuit(empty_pb2.Empty(), timeout=min(self._timeout, 2.0))
            return bool(resp.should_quit)
        except grpc.RpcError:
            # server 抖一下不要直接判 quit
            return False

    # ---------------------------
    # Internal
    # ---------------------------
    def _ensure_ready(self):
        if self._stub is None or self._channel is None or not self._connected:
            raise RuntimeError("SimWrapper not initialized. Call init() first.")

    def _close(self):
        if self._channel is not None:
            with contextlib.suppress(Exception):
                self._channel.close()
        self._channel = None
        self._stub = None
