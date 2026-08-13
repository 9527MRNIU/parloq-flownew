package lease

import (
	"context"
	"errors"
	"fmt"
	"strconv"
	"time"

	"github.com/redis/go-redis/v9"
)

var acquireScript = redis.NewScript(`
if redis.call('EXISTS', KEYS[1]) == 1 then
  return nil
end
local now = redis.call('TIME')
local candidate = (tonumber(now[1]) * 1000) + math.floor(tonumber(now[2]) / 1000)
local previous = tonumber(redis.call('GET', KEYS[2]) or '0')
if previous >= candidate then
  candidate = previous + 1
end
local value = ARGV[1] .. ':' .. tostring(candidate)
redis.call('SET', KEYS[2], tostring(candidate))
redis.call('PSETEX', KEYS[1], ARGV[2], value)
return {value, tostring(candidate)}
`)

var renewScript = redis.NewScript(`
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('PEXPIRE', KEYS[1], ARGV[2])
end
return 0
`)

var releaseScript = redis.NewScript(`
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
`)

type RedisManager struct {
	client     *redis.Client
	ttl        time.Duration
	instanceID string
}

func NewRedisManager(redisURL, instanceID string, ttl time.Duration) (*RedisManager, error) {
	options, err := redis.ParseURL(redisURL)
	if err != nil {
		return nil, fmt.Errorf("parse Redis URL: %w", err)
	}
	return &RedisManager{
		client:     redis.NewClient(options),
		ttl:        ttl,
		instanceID: instanceID,
	}, nil
}

func (m *RedisManager) Close() error { return m.client.Close() }

func (m *RedisManager) Ready(ctx context.Context) error {
	return m.client.Ping(ctx).Err()
}

func (m *RedisManager) Acquire(ctx context.Context, accountID string) (Lease, error) {
	owner := m.instanceID + ":" + strconv.FormatInt(time.Now().UnixNano(), 36)
	result, err := acquireScript.Run(ctx, m.client,
		[]string{leaseKey(accountID), epochKey(accountID)},
		owner, m.ttl.Milliseconds(),
	).Slice()
	if errors.Is(err, redis.Nil) || (err == nil && len(result) == 0) {
		return Lease{}, ErrUnavailable
	}
	if err != nil {
		return Lease{}, err
	}
	if len(result) != 2 {
		return Lease{}, fmt.Errorf("unexpected Redis lease response")
	}
	value := fmt.Sprint(result[0])
	epoch, err := strconv.ParseInt(fmt.Sprint(result[1]), 10, 64)
	if err != nil {
		return Lease{}, fmt.Errorf("parse Redis lease epoch: %w", err)
	}
	return Lease{AccountID: accountID, Value: value, Epoch: epoch}, nil
}

func (m *RedisManager) Renew(ctx context.Context, current Lease) (bool, error) {
	result, err := renewScript.Run(ctx, m.client,
		[]string{leaseKey(current.AccountID)}, current.Value, m.ttl.Milliseconds(),
	).Int64()
	return result == 1, err
}

func (m *RedisManager) Release(ctx context.Context, current Lease) (bool, error) {
	result, err := releaseScript.Run(ctx, m.client,
		[]string{leaseKey(current.AccountID)}, current.Value,
	).Int64()
	return result == 1, err
}

func leaseKey(accountID string) string { return "wa-gateway:account:" + accountID + ":lease" }
func epochKey(accountID string) string { return "wa-gateway:account:" + accountID + ":lease-epoch" }
