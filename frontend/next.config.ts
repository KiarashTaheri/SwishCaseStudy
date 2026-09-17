import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /*
   * `next dev` otherwise writes AGENTS.md and CLAUDE.md into this directory on
   * every start. They document Next's own conventions for AI tools, which is
   * reasonable in a working repo and confusing in a take-home — a reviewer
   * finds two files nobody in this project wrote, describing rules nothing here
   * follows. Off, so the tree contains only what was written for the exercise.
   */
  agentRules: false,
};

export default nextConfig;
