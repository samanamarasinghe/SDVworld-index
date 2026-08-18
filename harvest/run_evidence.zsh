#!/bin/zsh
# Run harvest/repo_evidence.py over the uncurated repo pool in N parallel slices.
#
#     ./harvest/run_evidence.zsh        # 8 slices
#     ./harvest/run_evidence.zsh 12     # 12 slices
#
# Evidence lands in harvest/evidence/ (one JSON per repo), logs in harvest/logs/.
# No GITHUB_TOKEN needed: repo_evidence.py fetches tarballs and partial clones.
#
# --uncurated drops any repo that already has an entry in data/sdv-index.json,
# so this visits the tail only. Drop the flag to re-harvest curated repos too.
#
# Resumable. --skip-existing leaves any repo that already has an ok record alone,
# so re-running after an interrupt picks up where it stopped. Records that failed
# ARE retried; to force a full re-harvest, empty harvest/evidence/ first.
#
# Run this only after github_tail.py and github_metrics.py have finished. Slice
# membership is computed from data/tail/github-repos.json when each process
# starts, so a pool that changes mid-pass reshuffles the slices and repos get
# done twice or not at all. And a repo with no disk_kb yet is fetched as a
# tarball however large it is, which is what metrics is there to prevent.

set -e
cd ${0:A:h:h}          # repo root, whatever directory this was called from

N=${1:-8}
mkdir -p harvest/logs harvest/evidence

pids=()
trap 'print "\ninterrupted, stopping slices"; kill ${pids} 2>/dev/null; exit 130' INT TERM

for k in {1..$N}; do
  python3 harvest/repo_evidence.py --slice $k/$N --uncurated --skip-existing \
    > harvest/logs/slice-$k-of-$N.log 2>&1 &
  pids+=($!)
  print "started slice $k/$N (pid $!)"
done

print "\nrunning; follow with: tail -f harvest/logs/slice-1-of-$N.log"

failed=0
for pid in ${pids}; do
  wait $pid || failed=$((failed + 1))
done

n_files=$(ls harvest/evidence/*.json 2>/dev/null | wc -l | tr -d ' ')
print "\ndone: ${n_files} evidence files, ${failed} slice(s) exited non-zero"

n_err=$(grep -h ' error ' harvest/logs/slice-*-of-$N.log 2>/dev/null | wc -l | tr -d ' ')
print "per-repo failures: ${n_err}  (grep ' error ' harvest/logs/slice-*.log to see them)"
