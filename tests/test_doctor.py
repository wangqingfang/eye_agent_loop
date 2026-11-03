"""环境检查（agentloop doctor）与机器绑定。"""

import json
import platform

from agentloop import cli, doctor


def _fp(proj, bind, dir_, encoding="utf-8"):
    (proj / ".环境").mkdir(parents=True, exist_ok=True)
    (proj / ".环境" / "机器指纹.txt").write_text(f"BIND={bind}\nDIR={dir_}\nINSTALLED=2026-11-03\n", encoding=encoding)


def test_binding_matches_current_machine(tmp_path):
    info = doctor.machine_info(tmp_path)
    _fp(tmp_path, info["绑定标识"], tmp_path)
    assert doctor.binding_status(tmp_path, info)[0] == doctor.PASS


def test_binding_detects_other_machine(tmp_path):
    info = doctor.machine_info(tmp_path)
    _fp(tmp_path, "Windows-AMD64" if platform.system() != "Windows" else "Darwin-arm64", tmp_path)
    result, note = doctor.binding_status(tmp_path, info)
    assert result == doctor.FAIL and "另一台机器" in note


def test_binding_detects_moved_folder(tmp_path):
    info = doctor.machine_info(tmp_path)
    _fp(tmp_path, info["绑定标识"], tmp_path / "旧位置")
    assert doctor.binding_status(tmp_path, info)[0] == doctor.WARN


def test_binding_missing_install_record(tmp_path):
    assert doctor.binding_status(tmp_path, doctor.machine_info(tmp_path))[0] == doctor.WARN


def test_fingerprint_written_by_windows_in_gbk_is_readable(tmp_path):
    _fp(tmp_path, "Windows-AMD64", "C:\\用户\\桌面\\AgentLoop\\", encoding="gbk")
    assert doctor.read_fingerprint(tmp_path)["DIR"] == "C:\\用户\\桌面\\AgentLoop\\"


def test_machine_command_prints_json(capsys):
    cli.main(["doctor", "--machine"])
    info = json.loads(capsys.readouterr().out)
    assert {"操作系统", "处理器架构", "绑定标识", "Python", "机器绑定"} <= set(info)


def test_quick_check_passes_in_dev_environment(capsys):
    assert cli.main(["doctor", "--quick"]) == 0
    out = capsys.readouterr().out
    assert "【通过】依赖包" in out and "【通过】数据字典" in out


def test_selftest_runs_offline():
    name, result, note = doctor.check_selftest()
    assert result == doctor.PASS, note
