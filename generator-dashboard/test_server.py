import tempfile, unittest
from pathlib import Path
from aiohttp.test_utils import AioHTTPTestCase
from server import Reader, create_app

class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.now=0.0;self.reader=Reader(self.temp.name,clock=lambda:self.now)
    def feed(self,t,v): self.now=t;self.reader.ingest(v)
    def test_disconnected_and_invalid_attempts(self):
        with self.assertRaises(ValueError): self.reader.start('Team A',15)
        self.feed(0,1)
        for name,seconds in [('',15),('A',12),('A',True),('x'*61,15)]:
            with self.assertRaises(ValueError): self.reader.start(name,seconds)
        self.reader.start(' Team A ',15)
        with self.assertRaises(ValueError): self.reader.start('Team B',15)
    def test_weighted_average_and_persistence(self):
        self.feed(0,1);self.reader.start('Team A',15)
        self.feed(.5,3);self.now=1;run=self.reader.finish('stopped')
        self.assertAlmostEqual(run['average'],2.5)
        self.assertEqual(run['peak'],3)
        recovered=Reader(self.temp.name)
        self.assertEqual(recovered.runs[0]['team'],'Team A')
        self.assertEqual(len(recovered.runs[0]['samples']),2)
        self.assertFalse((Path(self.temp.name)/'active.json').exists())
    def test_complete_attempt_and_saturation(self):
        self.feed(0,1);self.reader.start('Team A',15)
        for i in range(1,76):
            self.feed(i*.2,3.12 if i==20 else 1);self.reader.tick()
        self.assertIsNone(self.reader.active)
        self.assertEqual(self.reader.runs[0]['status'],'complete')
        self.assertEqual(self.reader.runs[0]['elapsed'],15)
        self.assertTrue(self.reader.runs[0]['clipped'])
    def test_gap_does_not_become_a_valid_score(self):
        self.feed(0,1);self.reader.start('Team A',15)
        self.feed(3,2)
        self.assertIsNone(self.reader.active)
        self.assertEqual(self.reader.runs[0]['status'],'interrupted')
    def test_link_loss_and_restart_recovery(self):
        self.feed(0,1);self.reader.start('Team A',15)
        restored=Reader(self.temp.name)
        self.assertEqual(restored.runs[0]['status'],'interrupted')
        self.assertEqual(restored.runs[0]['team'],'Team A')
        self.reader.connected=False;self.reader.tick()
        self.assertIsNone(self.reader.active)
    def test_nan_does_not_poison_data(self):
        self.feed(0,float('nan'))
        self.assertFalse(self.reader.samples)

class APITests(AioHTTPTestCase):
    async def get_application(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.reader=Reader(self.temp.name)
        return create_app(self.reader,connect=False)
    async def test_lifecycle_and_export(self):
        self.reader.ingest(1.5)
        result=await self.client.post('/api/runs/start',json={'team':'Test team','duration':15})
        self.assertEqual(result.status,200);run=await result.json()
        stop=await self.client.post('/api/runs/stop',json={});self.assertEqual(stop.status,200)
        detail=await self.client.get('/api/runs/'+run['id']);self.assertEqual(detail.status,200)
        csv=await self.client.get('/api/runs/'+run['id']+'/csv')
        self.assertIn('elapsed_seconds,voltage_volts',await csv.text())
        self.assertEqual((await self.client.get('/api/runs/not-a-run')).status,404)
    async def test_reset_preserves_results_and_protects_active_attempt(self):
        self.reader.ingest(1.5)
        self.reader.start('Saved team',15);self.reader.finish()
        result=await self.client.post('/api/reset',json={})
        self.assertEqual(result.status,200)
        state=await result.json()
        self.assertEqual(state['samples'],[])
        self.assertEqual(len(state['runs']),1)
        # Starting before the next packet must fail cleanly, not index an empty buffer.
        start=await self.client.post('/api/runs/start',json={'team':'Next','duration':15})
        self.assertEqual(start.status,400)
        self.reader.ingest(.5)
        self.reader.start('Next',15)
        result=await self.client.post('/api/reset',json={})
        self.assertEqual(result.status,400)
        self.assertIsNotNone(self.reader.active)
        self.assertEqual(len(self.reader.samples),1)

    async def test_validation_and_cross_origin(self):
        self.assertEqual((await self.client.post('/api/runs/start',json={})).status,400)
        self.assertEqual((await self.client.post('/api/runs/start',json={},headers={'Origin':'https://unrelated.example'})).status,403)
        self.assertEqual((await self.client.post('/api/runs/start',data='team=A')).status,415)
if __name__=='__main__': unittest.main()
