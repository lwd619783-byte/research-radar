"""Execute the real motion functions: final data and missing values must survive."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

APP = (Path(__file__).resolve().parents[1] / 'site/app.js').read_text(encoding='utf-8')
NODE = shutil.which('node')


def function(name, following):
    start = APP.index('function ' + name + '(')
    return APP[start:APP.index(following, start)]


FUNCTIONS = function('countUp', 'const phaseText') + function('animateRadar', 'function findCo')
HARNESS = '''
let time=0,reduced=false,next=1,radarFrame=0,RC=[0,0,0,0],draws=[];
const pending=new Map(),performance={now:()=>time},RM=()=>reduced;
const requestAnimationFrame=f=>{const id=next++;pending.set(id,f);return id};
const cancelAnimationFrame=id=>pending.delete(id),drawRadar=v=>draws.push(v.slice());
const step=t=>{time=t;const frames=[...pending.values()];pending.clear();frames.forEach(f=>f(t))};
'''


class MotionValueTests(unittest.TestCase):
    def execute(self, script):
        self.assertIsNotNone(NODE, 'Node.js is required for frontend value regressions')
        result = subprocess.run([NODE, '-e', HARNESS + FUNCTIONS + script],
                                check=True, capture_output=True, text=True)
        return json.loads(result.stdout)

    def test_counter_finishes_at_exact_source_value(self):
        value = self.execute('''
const el={dataset:{count:'17.923082',dp:'6',suf:'%'},textContent:'17.923082%'};
countUp(el);step(300);const moving=el.textContent;step(1200);
process.stdout.write(JSON.stringify([moving,el.textContent,el.dataset.count,pending.size]));
''')
        self.assertNotEqual(value[0], '17.923082%')
        self.assertEqual(value[1:], ['17.923082%', '17.923082', 0])

    def test_missing_values_stay_missing_and_real_zero_stays_zero(self):
        value = self.execute('''
const missing=['','null','undefined','NaN'].map(count=>({dataset:{count},textContent:'—'}));
missing.forEach(countUp);const before=pending.size;
reduced=true;const zero={dataset:{count:'0'},textContent:'0'};countUp(zero);
process.stdout.write(JSON.stringify([missing.map(x=>x.textContent),before,zero.textContent]));
''')
        self.assertEqual(value, [['—', '—', '—', '—'], 0, '0'])

    def test_rapid_radar_selection_cancels_previous_target(self):
        value = self.execute('''
const first=[5,5,5,5],latest=[1,2,3,4];animateRadar(first);step(350);
animateRadar(latest);step(1050);step(2000);
process.stdout.write(JSON.stringify([RC,draws.at(-1),pending.size,first,latest]));
''')
        self.assertEqual(value, [[1, 2, 3, 4], [1, 2, 3, 4], 0, [5, 5, 5, 5], [1, 2, 3, 4]])

    def test_reduced_motion_renders_final_values_without_frames(self):
        value = self.execute('''
reduced=true;animateRadar([5,4,3,2]);
const el={dataset:{count:'42.5',dp:'2'},textContent:'42.50'};countUp(el);
process.stdout.write(JSON.stringify([RC,draws.at(-1),el.textContent,pending.size]));
''')
        self.assertEqual(value, [[5, 4, 3, 2], [5, 4, 3, 2], '42.50', 0])

    def test_reduced_motion_change_finishes_running_effects(self):
        value = self.execute('''
const el={dataset:{count:'18'},textContent:'18'};countUp(el);animateRadar([4,5,3,2]);
step(100);reduced=true;step(116);
process.stdout.write(JSON.stringify([el.textContent,RC,pending.size]));
''')
        self.assertEqual(value, ['18', [4, 5, 3, 2], 0])


if __name__ == '__main__':
    unittest.main()
