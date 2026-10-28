"""Upload a built gallery: Cloudflare Pages, or S3 + CloudFront (stack from infra/aws-gallery.yaml)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .gallery import ASSET_FOLDERS, BEACON

AWS_PROFILE = "event-photos"  # `aws configure --profile event-photos` with the stack's publisher key
IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"  # pages: browsers and CloudFront check for a new version on every visit
PAGES = ("robots.txt", "index.html")  # index.html last, once every photo it points to is up


def cloudflare_pages(site: Path, project: str) -> None:
    """Creates the Pages project on first use."""
    wrangler = ["npx", "--yes", "wrangler", "pages"]
    projects = subprocess.run([*wrangler, "project", "list", "--json"], capture_output=True, text=True, check=True)
    if project not in {p.get("Project Name") for p in json.loads(projects.stdout)}:
        # --force: create a classic Pages project instead of wrangler's delegation to Workers
        subprocess.run([*wrangler, "project", "create", project, "--production-branch", "main", "--force"], check=True)
    cmd = [*wrangler, "deploy", str(site), "--project-name", project, "--branch", "main", "--commit-dirty=true"]
    subprocess.run(cmd, check=True)


def stack_outputs(stack: str, profile: str = AWS_PROFILE) -> dict[str, str]:
    out = subprocess.run(["aws", "cloudformation", "describe-stacks", "--stack-name", stack,
                          "--query", "Stacks[0].Outputs", "--output", "json", "--profile", profile],
                         capture_output=True, text=True, check=True)
    return {o["OutputKey"]: o["OutputValue"] for o in json.loads(out.stdout)}


def aws_commands(site: Path, bucket: str, distribution: str, profile: str = AWS_PROFILE) -> list[list[str]]:
    """Photos first, then the pages that reference them, then drop what the new build no longer has."""
    aws = ["aws", "--profile", profile]
    cmds = [[*aws, "s3", "sync", str(site / folder), f"s3://{bucket}/{folder}", "--cache-control", IMMUTABLE]
            for folder in ASSET_FOLDERS if (site / folder).is_dir()]
    if (site / BEACON).is_file():  # the counts' GIF never changes; the edge answers it and the log still records it
        cmds.append([*aws, "s3", "cp", str(site / BEACON), f"s3://{bucket}/{BEACON}", "--cache-control", IMMUTABLE])
    cmds += [[*aws, "s3", "cp", str(site / page), f"s3://{bucket}/{page}", "--cache-control", REVALIDATE]
             for page in PAGES]
    # --size-only: everything was just uploaded, so this pass only deletes leftovers
    cmds.append([*aws, "s3", "sync", str(site), f"s3://{bucket}", "--delete", "--size-only",
                 "--exclude", "_headers"])
    cmds.append([*aws, "cloudfront", "create-invalidation", "--distribution-id", distribution,
                 "--paths", "/*", "--query", "Invalidation.Id", "--output", "text"])
    return cmds


def aws(site: Path, stack: str, profile: str = AWS_PROFILE) -> str:
    outputs = stack_outputs(stack, profile)
    for cmd in aws_commands(site, outputs["BucketName"], outputs["DistributionId"], profile):
        subprocess.run(cmd, check=True)
    return outputs["Url"]
