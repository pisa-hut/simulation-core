import contextlib
import logging
import time

import grpc
from google.protobuf.struct_pb2 import Struct
from pisa_api import (
    av_server_pb2,
    av_server_pb2_grpc,
    config_pb2,
    empty_pb2,
    path_pb2,
)

from simcore.execution import ShouldQuitResult, classify_grpc_error
from simcore.runtime_actors import PreparedObservation
from simcore.utils.sps import ScenarioPack
from simcore.utils.util import get_cfg

logger = logging.getLogger(__name__)


class AVWrapper:
    def __init__(
        self,
        av_spec: dict,
        map_name: str,
        dt_ns: int = None,
    ):
        self._av_spec = av_spec
        self._map_name = map_name

        if dt_ns is None:
            logger.warning("dt not specified for AVWrapper, defaulting to 0.01s")
            self._dt_s = 0.01
        else:
            self._dt_s = dt_ns / 1e9

        self._url = self._av_spec.get("url", "localhost:50052")
        self._timeout = float(self._av_spec.get("timeout", 100.0))
        self._av_cfg_path = self._av_spec.get("config_path", None)
        self._av_output_dir = self._av_spec.get("output_path", "/mnt/output")

        if self._av_cfg_path is not None:
            self._av_cfg = get_cfg(self._av_cfg_path)
        else:
            self._av_cfg = None

        # long-lived channel
        self._channel = grpc.insecure_channel(self._url)
        self._stub = av_server_pb2_grpc.AvServerStub(self._channel)
        while True:
            try:
                pong = self._stub.Ping(empty_pb2.Empty(), timeout=self._timeout)
                logger.info(f"AV ping response: {pong.msg}")
                break
            except Exception:
                logger.warning("AV ping failed, retrying...")
                time.sleep(2)
        logger.info("AV service is alive")
        self._connected = True

        self.init()

    # ---------------------------
    # Public API
    # ---------------------------

    def init(self):
        cfg_struct = Struct()
        cfg_struct.update(self._av_cfg if self._av_cfg is not None else {})
        config = config_pb2.Config(config=cfg_struct)
        request = av_server_pb2.AvServerMessages.InitRequest(
            config=config,
            output_dir=path_pb2.Path(path=str(self._av_output_dir)),
            map_name=self._map_name,
            dt=self._dt_s,
        )
        try:
            self._stub.Init(request, timeout=self._timeout)
        except grpc.RpcError as e:
            raise classify_grpc_error(e) from e
        logger.info("AV init completed")

    def reset(
        self,
        output_dir: str,
        sps: ScenarioPack,
        init_obs: PreparedObservation,
    ):
        self._sps = sps
        self._ensure_ready()
        req = av_server_pb2.AvServerMessages.ResetRequest(
            output_dir=path_pb2.Path(path=str(output_dir)),
            scenario_pack=self._sps.to_protobuf(),
        )
        self._copy_observation(req.initial_observation, init_obs)
        try:
            resp = self._stub.Reset(req, timeout=self._timeout)
            return resp.ctrl_cmd
        except grpc.RpcError as e:
            raise classify_grpc_error(e) from e

    def step(self, obs: PreparedObservation, time_stamp_ns: int):
        self._ensure_ready()

        req = av_server_pb2.AvServerMessages.StepRequest(timestamp_ns=int(time_stamp_ns))
        self._copy_observation(req.observation, obs)
        try:
            resp = self._stub.Step(req, timeout=self._timeout)
            return resp.ctrl_cmd
        except grpc.RpcError as e:
            raise classify_grpc_error(e) from e

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

    def should_quit(self) -> ShouldQuitResult:
        """
        rpc ShouldQuit(Empty) returns (ShouldQuitResponse)
        """
        if self._stub is None or not self._connected:
            return ShouldQuitResult(True, "AV wrapper is not connected")
        try:
            resp = self._stub.ShouldQuit(empty_pb2.Empty(), timeout=min(self._timeout, 2.0))
            return ShouldQuitResult(bool(resp.should_quit), getattr(resp, "msg", ""))
        except grpc.RpcError:
            # server 抖一下不要直接判 quit
            return ShouldQuitResult(False)

    # ---------------------------
    # Internal
    # ---------------------------
    def _ensure_ready(self):
        if self._stub is None or self._channel is None or not self._connected:
            raise RuntimeError("AvWrapper not initialized. Call init() first.")

    @staticmethod
    def _copy_observation(target, observation: PreparedObservation) -> None:
        """Populate the breaking v2 Observation protobuf without importing it eagerly."""

        if not hasattr(target, "ego") or not hasattr(target, "agents"):
            raise RuntimeError(
                "Installed pisa-api does not provide the v2 Observation contract. "
                "Upgrade pisa-api and the AV server together."
            )
        target.ego.CopyFrom(observation.ego)
        for observed in observation.agents:
            entry = target.agents.add()
            entry.state.CopyFrom(observed.state)
            if observed.tracking_id is not None:
                entry.tracking_id = observed.tracking_id
            if observed.entity_name is not None:
                entry.entity_name = observed.entity_name

    def _close(self):
        if self._channel is not None:
            with contextlib.suppress(Exception):
                self._channel.close()
        self._channel = None
        self._stub = None
