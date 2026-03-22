import {
  Brain,
  Search,
  BarChart3,
  GitBranch,
  Puzzle,
  Cpu,
  Database,
  FileText,
  FunctionSquare,
  Globe,
  MessageSquare,
  Shield,
  User,
  Zap,
  type LucideProps,
} from "lucide-react";
import type { ComponentType } from "react";

const ICON_MAP: Record<string, ComponentType<LucideProps>> = {
  brain: Brain,
  search: Search,
  database: BarChart3,
  "git-branch": GitBranch,
  puzzle: Puzzle,
  cpu: Cpu,
  db: Database,
  "file-text": FileText,
  globe: Globe,
  message: MessageSquare,
  "function-square": FunctionSquare,
  shield: Shield,
  user: User,
  zap: Zap,
};

interface Props {
  name: string;
  size?: number;
  className?: string;
}

export function NodeIcon({ name, size = 16, className }: Props) {
  const Icon = ICON_MAP[name] ?? Puzzle;
  return <Icon size={size} strokeWidth={2} className={className} />;
}
