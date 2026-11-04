"""打包分发：Windows 解压不乱码。"""

import zipfile

from conftest import PROJECT

from agentloop import pack


def test_pack_sets_utf8_flag_and_keeps_bytes(tmp_path):
    out = pack.build(PROJECT, tmp_path / "x.zip")
    assert pack.verify(PROJECT, out) == []
    with zipfile.ZipFile(out) as z:
        infos = z.infolist()
        cjk = [i for i in infos if any(ord(c) > 127 for c in i.filename)]
        assert cjk and all(i.flag_bits & pack.UTF8_FLAG for i in cjk)
        names = {i.filename for i in infos}
        bat = z.read("eye_agent_loop/启动研究.bat")
    assert b"\r\n" in bat and bat.decode("gbk")  # GBK + CRLF 原样保留
    assert not any(part in n for n in names for part in ("/.venv/", "/.git/", "/runs/", "/配置.txt"))
    assert "eye_agent_loop/资料/干眼共病模型_数据字典_V1.0.xlsx" in names


def test_collect_without_git_uses_same_excludes(tmp_path):
    (tmp_path / "资料").mkdir()
    (tmp_path / "资料" / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "配置.txt").write_text("API_KEY=sk-secret", encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "python").write_text("", encoding="utf-8")
    assert pack.collect(tmp_path) == ["资料/a.txt"]
