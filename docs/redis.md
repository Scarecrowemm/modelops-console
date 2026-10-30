# Redis 限流（可选）

默认是进程内固定窗口，单机 demo 足够。设置一个环境变量就会切到 Redis：

```bash
$env:MODELOPS_REDIS_URL="redis://127.0.0.1:6379/0"
```

本地起一个 Redis：

```bash
docker run --rm -p 6379:6379 redis:7
```

## 实现

`app/ratelimit_redis.py`：

- 每个租户、每分钟两个 key：`rl:{tenant}:rpm:{window}`、`rl:{tenant}:tpm:{window}`；
- `INCR` / `INCRBY` + `EXPIRE 120`；
- 超过 RPM/TPM 返回 429 和 `Retry-After`；
- Redis 连不上、包没装、命令报错时，自动回退到进程内 `RateLimiter`，demo 不会挂。

## 注意

- 这是 `INCR + EXPIRE`，不是 Lua 原子脚本；高并发边界会有误差。
- 没有做连接池、熔断、多副本一致性。
- 测试里用了一个不存在的端口，验证“连不上时回退”这条路径（`tests/test_redis_limiter.py`）。
