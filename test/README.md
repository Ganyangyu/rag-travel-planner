# 测试

离线回归（不调用真实模型和网页）：

```powershell
python -m unittest discover -s test -p "test_*.py" -v
```

独立联网测试（使用共享或个人账号额度）：

```powershell
python test/test_qwen.py
python test/test_crawler.py --city "上海" --date "2026-12-01" --days 5 --budget 1000 --audience "老年人"
python -m src.crawler --diagnose
```

正文测试要求至少三篇不同可读资料；标题记录不计数。网络受限或会话失效会返回实际诊断，测试成功不代表所有城市和网络均可访问。
