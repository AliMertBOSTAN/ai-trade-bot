import { useEffect, useRef } from 'react'
import {
  Chart,
  LineController,
  LineElement,
  PointElement,
  LinearScale,
  TimeSeriesScale,
  CategoryScale,
  Tooltip,
  Filler
} from 'chart.js'

Chart.register(
  LineController,
  LineElement,
  PointElement,
  LinearScale,
  CategoryScale,
  TimeSeriesScale,
  Tooltip,
  Filler
)

export default function EquityChart({ data }: { data: { t: number; equity: number }[] }): JSX.Element {
  const ref = useRef<HTMLCanvasElement>(null)
  const chartRef = useRef<Chart | null>(null)

  useEffect(() => {
    if (!ref.current) return
    const labels = data.map((d) => new Date(d.t).toLocaleTimeString())
    const values = data.map((d) => d.equity)

    if (chartRef.current) {
      chartRef.current.data.labels = labels
      chartRef.current.data.datasets[0].data = values
      chartRef.current.update('none')
      return
    }

    const ctx = ref.current.getContext('2d')
    let fill: CanvasGradient | string = 'rgba(52,211,153,0.10)'
    if (ctx) {
      const g = ctx.createLinearGradient(0, 0, 0, 250)
      g.addColorStop(0, 'rgba(52, 211, 153, 0.28)')
      g.addColorStop(0.6, 'rgba(52, 211, 153, 0.06)')
      g.addColorStop(1, 'rgba(52, 211, 153, 0)')
      fill = g
    }

    chartRef.current = new Chart(ref.current, {
      type: 'line',
      data: {
        labels,
        datasets: [
          {
            label: 'Equity (USD)',
            data: values,
            borderColor: '#34d399',
            backgroundColor: fill,
            fill: true,
            tension: 0.32,
            pointRadius: 0,
            pointHoverRadius: 4,
            pointHoverBackgroundColor: '#34d399',
            pointHoverBorderColor: '#07090f',
            pointHoverBorderWidth: 2,
            borderWidth: 2.25
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: 'rgba(15, 20, 31, 0.95)',
            borderColor: 'rgba(106, 166, 255, 0.25)',
            borderWidth: 1,
            titleColor: '#9fb0c9',
            bodyColor: '#e2e8f3',
            padding: 10,
            cornerRadius: 10,
            displayColors: false,
            callbacks: {
              label: (item) =>
                ` ${Number(item.parsed.y).toLocaleString('en-US', {
                  style: 'currency',
                  currency: 'USD'
                })}`
            }
          }
        },
        scales: {
          x: {
            ticks: { color: '#5b6680', maxTicksLimit: 8, font: { size: 10 } },
            grid: { display: false },
            border: { color: 'rgba(255,255,255,0.07)' }
          },
          y: {
            ticks: { color: '#5b6680', font: { size: 10 } },
            grid: { color: 'rgba(255,255,255,0.045)' },
            border: { display: false, dash: [4, 4] }
          }
        }
      }
    })
  }, [data])

  useEffect(() => () => chartRef.current?.destroy(), [])

  return <canvas ref={ref} />
}
