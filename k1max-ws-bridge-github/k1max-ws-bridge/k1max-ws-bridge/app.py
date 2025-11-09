import asyncio
import json
import time
from typing import Any, Dict
import websockets
from websockets.exceptions import ConnectionClosedError, InvalidURI, InvalidStatusCode
import paho.mqtt.client as mqtt
from jsonpath_ng import parse as jp

OPTIONS_PATH = "/data/options.json"

def log(msg: str):
    print(f"[k1max-ws-bridge] {msg}", flush=True)

def load_options() -> Dict[str, Any]:
    with open(OPTIONS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def to_discovery(sensor, cfg):
    disc = {
        "name": sensor["name"],
        "state_topic": f'{cfg["base_topic"]}/state/{sensor["unique_id"]}',
        "unique_id": sensor["unique_id"],
        "device": {
            "identifiers": [cfg["device_id"]],
            "manufacturer": "Creality",
            "name": cfg["device_name"],
            "model": "K1/K1 Max (WS Bridge)",
        },
        "icon": sensor.get("icon") or "mdi:printer-3d",
    }
    if sensor.get("unit"):
        disc["unit_of_measurement"] = sensor["unit"]
    if sensor.get("device_class"):
        disc["device_class"] = sensor["device_class"]
    if sensor.get("state_class"):
        disc["state_class"] = sensor["state_class"]
    return disc

def transform_value(x, mode: str):
    if x is None:
        return None
    try:
        if mode == "percent_0_1_to_0_100":
            val = float(x)
            return round(val * 100.0, 2) if 0.0 <= val <= 1.0 else round(val, 2)
        if mode == "seconds_to_hms":
            s = int(float(x))
            h = s // 3600
            m = (s % 3600) // 60
            sec = s % 60
            return f"{h:02d}:{m:02d}:{sec:02d}"
        return x
    except Exception:
        return x

class Bridge:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.ws_url = cfg["ws_url"]
        self.ws_headers = {str(k): str(v) for k, v in (cfg.get("ws_headers") or {}).items()}
        self.maps = cfg.get("mappings", [])
        self.discovery_prefix = cfg["mqtt"]["discovery_prefix"]
        self.base_topic = cfg["base_topic"]
        self.debug = cfg.get("debug", {})
        self.raw_left = int(self.debug.get("raw_frames_limit", 0)) if self.debug.get("log_raw_frames") else 0

        self.mqttc = mqtt.Client(client_id=f"k1max-bridge-{int(time.time())}")
        self.mqttc.username_pw_set(cfg["mqtt"]["username"], cfg["mqtt"]["password"])
        self.mqttc.connect(cfg["mqtt"]["host"], int(cfg["mqtt"]["port"]), 60)
        self.mqttc.loop_start()

    def publish_discovery(self):
        for s in self.maps:
            disc = to_discovery(s, self.cfg)
            topic = f'{self.discovery_prefix}/sensor/{self.cfg["device_id"]}/{s["unique_id"]}/config'
            payload = json.dumps(disc, separators=(",", ":"))
            self.mqttc.publish(topic, payload=payload, qos=1, retain=True)
            log(f"Published discovery: {topic}")

    def publish_state(self, uid: str, value: Any):
        topic = f"{self.base_topic}/state/{uid}"
        payload = "" if value is None else str(value)
        self.mqttc.publish(topic, payload=payload, qos=0, retain=True)

    def extract_values(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        out = {}
        for s in self.maps:
            expr = jp(s["jsonpath"])
            matches = [m.value for m in expr.find(msg)]
            value = matches[0] if matches else None
            value = transform_value(value, s.get("transform", "none"))
            out[s["unique_id"]] = value
        return out

    async def ws_loop(self):
        backoff = 2
        while True:
            try:
                log(f"Connecting to WebSocket: {self.ws_url}")
                async with websockets.connect(self.ws_url, extra_headers=self.ws_headers) as ws:
                    log("WebSocket connected.")
                    self.publish_discovery()
                    backoff = 2
                    async for msg in ws:
                        try:
                            data = json.loads(msg)
                        except json.JSONDecodeError:
                            if self.raw_left > 0:
                                log(f"RAW(nonjson) = {msg[:500]}")
                                self.raw_left -= 1
                            continue
                        if self.raw_left > 0:
                            log(f"RAW(json) = {json.dumps(data)[:500]}")
                            self.raw_left -= 1
                        values = self.extract_values(data)
                        for uid, val in values.items():
                            self.publish_state(uid, val)
            except (ConnectionClosedError, InvalidURI, InvalidStatusCode, OSError) as e:
                log(f"WS error: {repr(e)} — retrying in {backoff}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

def main():
    cfg = load_options()
    b = Bridge(cfg)
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(b.ws_loop())
    finally:
        b.mqttc.loop_stop()
        b.mqttc.disconnect()

if __name__ == "__main__":
    main()
