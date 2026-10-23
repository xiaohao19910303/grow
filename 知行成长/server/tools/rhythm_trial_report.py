"""Read participant-initiated JSON exports and print aggregate counts only."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rhythm.trial import summarize


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('exports',type=Path,nargs='+')
    args=parser.parse_args();reports=[];experiment=None
    for path in args.exports:
        data=json.loads(path.read_text())
        if data.get('format')!='grow-rhythm-v1':parser.error('需要 grow-rhythm-v1 个人导出文件。')
        people={p['id']:p for p in data['enrollments']}
        for report in data['trial_reports']:
            person=people[report['participant_id']]
            if experiment is None:experiment=person['experiment_key']
            if person['experiment_key']!=experiment:parser.error('不同试验不能合并；请分轮传入导出文件。')
            reports.append(report)
    print(json.dumps(summarize(reports),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
