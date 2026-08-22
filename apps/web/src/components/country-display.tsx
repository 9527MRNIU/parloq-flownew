import getUnicodeFlagIcon from "country-flag-icons/unicode";
import { Globe2Icon } from "lucide-react";
import { countryOptions } from "../lib/countries";
import { cn } from "../lib/utils";

const COUNTRY_NAME_BY_CODE = new Map(
  countryOptions.map((option) => [
    option.value,
    option.label.split(" · ")[0] || option.value,
  ]),
);

export function countryDisplayName(code: string): string {
  const normalized = code.trim().toUpperCase();
  return COUNTRY_NAME_BY_CODE.get(normalized) || normalized || "-";
}

export function CountryFlag({ code }: { code: string }) {
  const normalized = code.trim().toUpperCase();
  if (!COUNTRY_NAME_BY_CODE.has(normalized)) {
    return <Globe2Icon aria-hidden="true" className="h-4 w-6 text-muted-foreground" />;
  }

  return (
    <span
      aria-hidden="true"
      className="inline-flex h-4 w-6 shrink-0 items-center justify-center overflow-hidden text-lg leading-none"
    >
      {getUnicodeFlagIcon(normalized)}
    </span>
  );
}

export function CountryDisplay({
  code,
  className,
}: {
  code: string;
  className?: string;
}) {
  return (
    <div className={cn("flex min-w-max items-center justify-center gap-2", className)}>
      <CountryFlag code={code} />
      <span>{countryDisplayName(code)}</span>
    </div>
  );
}
