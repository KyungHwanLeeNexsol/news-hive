interface ChangeRateProps {
  value: number | null | undefined;
}

export default function ChangeRate({ value }: ChangeRateProps) {
  if (value == null) {
    return <span className="text-[#999]">-</span>;
  }

  const formatted = `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
  const colorClass =
    value > 0 ? "text-rise" : value < 0 ? "text-fall" : "text-[#333]";

  return <span className={colorClass}>{formatted}</span>;
}
