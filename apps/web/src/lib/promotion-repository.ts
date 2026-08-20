export type RepositoryView = "local" | "repository";
export type RepositoryLocalStatus = "new" | "update" | "current" | "conflict";

export type LocalRepositorySource = {
  sequence: string;
  repository: string;
  ref: string;
  localStatus: Exclude<RepositoryLocalStatus, "new">;
  remoteVersion: string;
};

export type RemotePromotionArtifact = {
  id: string;
  sequence: string;
  kind: "template" | "integration";
  slug: string;
  source: string;
  sourceUrl: string;
  name: string;
  description: string;
  version: string;
  integrationKey: string;
  type: "script" | "iframe" | "";
  repository: string;
  ref: string;
  commitSha: string;
  sourceSha: string;
  fileCount: number;
  totalSize: number;
  localStatus: RepositoryLocalStatus;
  localId: string;
  localName: string;
  localVersion: string;
};

const object = (input: unknown) =>
  input && typeof input === "object" ? (input as Record<string, unknown>) : {};

const field = (row: Record<string, unknown>, ...keys: string[]) => {
  for (const key of keys) if (row[key] != null) return String(row[key]);
  return "";
};

export function localRepositorySourceRow(
  input: unknown,
): LocalRepositorySource | null {
  const row = object(input);
  const sequence = field(row, "sequence");
  const localStatus = field(row, "localStatus", "local_status");
  if (!sequence || !["update", "current", "conflict"].includes(localStatus)) {
    return null;
  }
  return {
    sequence,
    repository: field(row, "repository"),
    ref: field(row, "ref"),
    localStatus: localStatus as LocalRepositorySource["localStatus"],
    remoteVersion: field(row, "remoteVersion", "remote_version"),
  };
}

export function remotePromotionArtifactRow(input: unknown): RemotePromotionArtifact {
  const row = object(input);
  const kind = field(row, "kind");
  const type = field(row, "type");
  const localStatus = field(row, "localStatus", "local_status");
  return {
    id: field(row, "id"),
    sequence: field(row, "sequence"),
    kind: kind === "integration" ? "integration" : "template",
    slug: field(row, "slug"),
    source: field(row, "source"),
    sourceUrl: field(row, "sourceUrl", "source_url"),
    name: field(row, "name"),
    description: field(row, "description"),
    version: field(row, "version") || "1",
    integrationKey: field(row, "integrationKey", "integration_key"),
    type: type === "script" || type === "iframe" ? type : "",
    repository: field(row, "repository"),
    ref: field(row, "ref"),
    commitSha: field(row, "commitSha", "commit_sha"),
    sourceSha: field(row, "sourceSha", "source_sha"),
    fileCount: Number(row.fileCount ?? row.file_count ?? 0),
    totalSize: Number(row.totalSize ?? row.total_size ?? 0),
    localStatus:
      localStatus === "update" || localStatus === "current" || localStatus === "conflict"
        ? localStatus
        : "new",
    localId: field(row, "localId", "local_id"),
    localName: field(row, "localName", "local_name"),
    localVersion: field(row, "localVersion", "local_version"),
  };
}

export function formatRepositorySize(value: number) {
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}
