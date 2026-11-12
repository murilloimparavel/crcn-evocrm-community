#!/usr/bin/env python3
"""Exercise durable receipts against the deployed Auth image and fresh stores.

Run on the Docker host with --source pointing at the auth service checkout.
Only ephemeral containers/network and a host temporary directory are created.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid
import re
import sys

IMAGE = "ghcr.io/murilloimparavel/evo-auth-knowledge-release:sha-398bdeba32ed621cb31504fd4feaba6bd0ec7acf"


def run(args, *, check=True, timeout=180, capture=False):
    result = subprocess.run(args, check=False, timeout=timeout, text=True,
                            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                            stderr=subprocess.PIPE if capture else subprocess.DEVNULL)
    if check and result.returncode:
        if capture:
            output = (result.stdout or "") + "\n" + (result.stderr or "")
            detail = re.sub(r"(?i)(password|secret|token|api[_-]?key)(\s*[=:]\s*)\S+",
                            r"\1\2[redacted]", output)
            print("Disposable command failed:", " ".join(args[:8]), file=sys.stderr)
            print(detail[-1800:], file=sys.stderr)
        raise subprocess.CalledProcessError(result.returncode, args, result.stdout, result.stderr)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    required = [
        "app/models/sidekiq_job_receipt.rb",
        "config/initializers/sidekiq_completion_receipts.rb",
        "db/migrate/20261112000001_create_sidekiq_job_receipts.rb",
        "lib/sidekiq_completion_receipt_middleware.rb",
    ]
    if not all((source / name).is_file() for name in required):
        raise RuntimeError("Receipt implementation files are incomplete")
    if not (source / "spec/lib/sidekiq_completion_receipt_middleware_spec.rb").is_file():
        raise RuntimeError("Receipt middleware spec is missing")

    tag = "receiptqa" + uuid.uuid4().hex[:10]
    names = {key: tag + "-" + key for key in ("network", "postgres", "redis", "app", "worker")}
    temp = Path(tempfile.mkdtemp(prefix=tag + "-"))
    temp.chmod(0o777)
    out = temp / "performed"
    try:
        run(["docker", "network", "create", "--internal", names["network"]])
        run(["docker", "run", "-d", "--name", names["postgres"], "--network", names["network"],
             "--tmpfs", "/var/lib/postgresql/data", "-e", "POSTGRES_USER=postgres",
             "-e", "POSTGRES_PASSWORD=postgres", "-e", "POSTGRES_DB=evo_auth_service_test",
             "--health-cmd", "pg_isready -U postgres", "--health-interval", "2s",
             "--health-timeout", "2s", "--health-retries", "30", "pgvector/pgvector:pg16"])
        run(["docker", "run", "-d", "--name", names["redis"], "--network", names["network"],
             "redis:alpine"])
        run(["docker", "run", "-d", "--name", names["app"], "--network", names["network"],
             "-v", str(temp) + ":/receipt-test:rw", "-e", "RAILS_ENV=test",
             "-v", str(source / "spec") + ":/rails/spec:ro",
             "-e", "POSTGRES_HOST=" + names["postgres"], "-e", "POSTGRES_PORT=5432",
             "-e", "POSTGRES_DATABASE=evo_auth_service_test", "-e", "POSTGRES_USERNAME=postgres",
             "-e", "POSTGRES_PASSWORD=postgres", "-e", "REDIS_URL=redis://" + names["redis"] + ":6379/3",
             "-e", "DOORKEEPER_JWT_SECRET_KEY=isolated-test-only-secret-never-for-production",
             "--entrypoint", "sh", IMAGE, "-c", "while true; do sleep 3600; done"])
        for subdir in ("app/models", "config/initializers", "db/migrate", "lib"):
            run(["docker", "exec", names["app"], "mkdir", "-p", "/rails/" + subdir])
        for rel in required:
            run(["docker", "cp", str(source / rel), names["app"] + ":/rails/" + rel])

        deadline = time.time() + 90
        while time.time() < deadline:
            state = run(["docker", "inspect", "--format", "{{.State.Health.Status}}",
                         names["postgres"]], capture=True, check=False)
            if state.returncode == 0 and state.stdout.strip() == "healthy":
                break
            time.sleep(2)
        else:
            raise RuntimeError("Disposable PostgreSQL did not become healthy")

        def app(*cmd, timeout=600, capture=True):
            return run(["docker", "exec", "-u", "rails", names["app"], "bundle", "exec", *cmd],
                       timeout=timeout, capture=capture)

        app("rails", "db:prepare")
        specs = app("rspec", "spec/lib/sidekiq_completion_receipt_middleware_spec.rb")
        if "4 examples, 0 failures" not in specs.stdout:
            raise RuntimeError("Receipt middleware specs did not pass: " + specs.stdout[-800:])
        print("Disposable Auth RSpec: PASS (4 examples)", flush=True)
        script = temp / "direct.rb"
        script.write_text('''
job = {"jid"=>"durable-receipt-test", "class"=>"ActiveJob::QueueAdapters::SidekiqAdapter::JobWrapper", "wrapped"=>"Licensing::HeartbeatJob", "args"=>[{"job_class"=>"Licensing::HeartbeatJob", "arguments"=>[]}]}
middleware = SidekiqCompletionReceiptMiddleware.new
raise "perform return not propagated" unless middleware.call(nil, job, "licensing") { :ok } == :ok
receipt = SidekiqJobReceipt.find_by!(jid: job.fetch("jid"))
raise "incorrect receipt class" unless receipt.job_class == "Licensing::HeartbeatJob"
raise "incorrect receipt queue" unless receipt.queue == "licensing"
raise "missing digest" unless receipt.payload_sha256.match?(/\\A[0-9a-f]{64}\\z/)
begin
  middleware.call(nil, job.merge("jid"=>"durable-receipt-failure"), "licensing") { raise "expected" }
rescue RuntimeError => e
  raise unless e.message == "expected"
end
raise "failed job got receipt" if SidekiqJobReceipt.exists?(jid: "durable-receipt-failure")
middleware.call(nil, job, "licensing") { raise "completed JID replayed" }
puts "PASS receipt success, failure, persistence and replay"
''')
        direct = app("rails", "runner", "/receipt-test/direct.rb")
        if "PASS receipt success" not in direct.stdout:
            raise RuntimeError("Direct durable receipt assertions did not pass")
        print("Disposable PostgreSQL: " + direct.stdout.strip().splitlines()[-1], flush=True)

        job_file = temp / "receipt_smoke_job.rb"
        job_file.write_text('''
class ReceiptSmokeJob
  include Sidekiq::Job
  def perform
    names = Sidekiq.default_configuration.server_middleware.map { |mw| mw.klass.name }
    File.open("/receipt-test/performed", "a") { |f| f.flock(File::LOCK_EX); f.puts(names.join(",")) }
  end
end
''')
        run(["docker", "cp", str(job_file), names["app"] + ":/receipt-test/receipt_smoke_job.rb"])
        bootstrap = temp / "worker_bootstrap.rb"
        bootstrap.write_text('require "/rails/config/environment"\nrequire "/receipt-test/receipt_smoke_job"\n')
        worker_cmd = ["docker", "run", "-d", "--name", names["worker"], "--network", names["network"],
                      "-v", str(temp) + ":/receipt-test:rw", "-e", "RAILS_ENV=test",
                      "-e", "POSTGRES_HOST=" + names["postgres"], "-e", "POSTGRES_PORT=5432",
                      "-e", "POSTGRES_DATABASE=evo_auth_service_test", "-e", "POSTGRES_USERNAME=postgres",
                      "-e", "POSTGRES_PASSWORD=postgres",
                      "-e", "DOORKEEPER_JWT_SECRET_KEY=isolated-test-only-secret-never-for-production",
                      "-e", "REDIS_URL=redis://" + names["redis"] + ":6379/3"]
        for rel in (required[0], required[1], required[3]):
            worker_cmd += ["-v", str(source / rel) + ":/rails/" + rel + ":ro"]
        worker_cmd += ["--entrypoint", "bundle", IMAGE, "exec", "sidekiq", "-r",
                       "/receipt-test/worker_bootstrap.rb", "-q", "receipt_smoke", "-c", "1", "-v"]
        run(worker_cmd)
        jid = app("rails", "runner", "-e", "test",
                  'puts "QA_JID=" + Sidekiq::Client.push("class"=>"ReceiptSmokeJob", "queue"=>"receipt_smoke", "args"=>[], "retry"=>false).to_s')
        import re
        match = re.search(r"QA_JID=([0-9a-f]{24})", jid.stdout)
        job_id = match.group(1) if match else None
        if not job_id:
            raise RuntimeError("Synthetic Sidekiq job did not enqueue")
        for _ in range(60):
            check = run(["docker", "exec", names["postgres"], "psql", "-U", "postgres",
                         "-d", "evo_auth_service_test", "-Atc",
                         "SELECT count(*) FROM sidekiq_job_receipts WHERE jid='" + job_id + "'"] ,
                        capture=True, check=False)
            if check.returncode == 0 and check.stdout.strip() == "1":
                break
            time.sleep(1)
        else:
            logs = run(["docker", "logs", names["worker"]], check=False, capture=True)
            observed = out.read_text().splitlines() if out.exists() else []
            raise RuntimeError("Worker did not persist receipt; job output=" + repr(observed) +
                               "; logs=" + (logs.stdout + logs.stderr)[-1600:])

        app("rails", "runner", "-e", "test",
            'Sidekiq::Client.push("class"=>"ReceiptSmokeJob", "jid"=>"' + job_id + '", "queue"=>"receipt_smoke", "args"=>[], "retry"=>false)')
        time.sleep(5)
        if not out.exists():
            raise RuntimeError("Synthetic Sidekiq job did not run")
        performed = out.read_text().splitlines()
        if sum("SidekiqCompletionReceiptMiddleware" in line for line in performed) != 1:
            raise RuntimeError("Sidekiq server middleware was not registered: " + repr(performed))
        if len(performed) != 1:
            raise RuntimeError("Real Sidekiq worker replayed a completed JID")
        print("PASS real Sidekiq job completed once; durable receipt suppressed same-JID replay", flush=True)
    finally:
        for key in ("worker", "app", "redis", "postgres"):
            subprocess.run(["docker", "rm", "-f", names[key]], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, check=False, timeout=60)
        subprocess.run(["docker", "network", "rm", names["network"]], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False, timeout=60)
        shutil.rmtree(temp)


if __name__ == "__main__":
    main()
