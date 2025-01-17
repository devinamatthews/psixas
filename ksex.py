# -*- coding: utf-8 -*-
"""
Created on Sun Aug 19 18:30:31 2018

@author: luke

Module to perform excited state calculations
"""
from .kshelper import diag_H,DIIS_helper,Timer
import numpy as np
import os
import psi4
import time

def DFTExcitedState(mol,func,orbitals,**kwargs):
    """
    Perform unrestrictred Kohn-Sham excited state calculation
    """
    psi4.core.print_out("\nEntering Excited State Kohn-Sham:\n"+33*"="+"\n\n")
  
    maxiter = int(psi4.core.get_local_option("PSIXAS","MAXITER"))
    E_conv  = 1.0E-8
    D_conv  = 1.0E-6


    """
    STEP 1: Read in ground state orbitals or restart from previous
    """
    prefix = psi4.core.get_local_option("PSIXAS","PREFIX")

    if (os.path.isfile(prefix+"_exorbs.npz") and False):
        psi4.core.print_out("Restarting Calculation\n")
        Ca = np.load(prefix+"_exorbs.npz")["Ca"]
        Cb = np.load(prefix+"_exorbs.npz")["Cb"]
    else:
        Ca = np.load(prefix+"_gsorbs.npz")["Ca"]
        Cb = np.load(prefix+"_gsorbs.npz")["Cb"]

    


    """
    Grep the coefficients for later overlap
    """

    for i in orbitals:
        if i["spin"]=="b":
            i["C"] = Cb[:,i["orb"]]
        elif i["spin"]=="a":
            i["C"] = Ca[:,i["orb"]]
        else:
            raise Exception("Orbital has non a/b spin!")


    wfn   = psi4.core.Wavefunction.build(mol,psi4.core.get_global_option('BASIS'))
    aux     = psi4.core.BasisSet.build(mol, "DF_BASIS_SCF", "", "JKFIT", psi4.core.get_global_option('BASIS'))

    #psi4.core.be_quiet()
    mints = psi4.core.MintsHelper(wfn.basisset())

    S = np.asarray(mints.ao_overlap())
    T = np.asarray(mints.ao_kinetic())
    V = np.asarray(mints.ao_potential())
    H = np.zeros((mints.nbf(),mints.nbf()))

    H = T+V

    A = mints.ao_overlap()
    A.power(-0.5,1.e-16)
    A = np.asarray(A)

    Enuc = mol.nuclear_repulsion_energy()
    Eold = 0.0
    SCF_E = 100.0
    nbf    = wfn.nso()
    nalpha = wfn.nalpha()
    nbeta  = wfn.nbeta()

    Va = psi4.core.Matrix(nbf,nbf)
    Vb = psi4.core.Matrix(nbf,nbf)

    sup = psi4.driver.dft.build_superfunctional(func, False)[0]
    sup.set_deriv(2)
    sup.allocate()

    Vpot = psi4.core.VBase.build(wfn.basisset(), sup, "UV")
    Vpot.initialize()

    #This object is needed to write out a molden file later
    uhf   = psi4.core.UHF(wfn,sup)
    psi4.core.reopen_outfile()
    """
    Form initial denisty
    """
    occa = np.zeros(Ca.shape[0])
    occb = np.zeros(Cb.shape[0])

    occa[:nalpha] = 1
    occb[:nbeta]  = 1

    Cocca = psi4.core.Matrix(nbf, nbf)
    Coccb = psi4.core.Matrix(nbf, nbf)

    Cocca.np[:]  = Ca
    Coccb.np[:]  = Cb

    for i in orbitals:
        if i["spin"]=="b":
            """
            Check if this is still the largest overlap
            """
            ovl = np.abs(np.einsum('m,nj,mn->j',i["C"],Coccb,S))
            if i["orb"] != np.argmax(ovl):
                print ("index changed from {:d} to {:d}".format(i["orb"],np.argmax(ovl)))
                i["orb"] = np.argmax(ovl)

            """
            Set occupation and overlap
            """
            i["ovl"] = np.max(ovl)
            occb[i["orb"]] = i["occ"]


        elif i["spin"]=="a":
            """
            Check if this is still the largest overlap
            """
            ovl = np.abs(np.einsum('m,nj,mn->j',i["C"],Cocca,S))
            if i["orb"] != np.argmax(ovl):
                print ("index changed from {:d} to {:d}".format(i["orb"],np.argmax(ovl)))
                i["orb"] = np.argmax(ovl)
            """
            Set occupation and overlap
            """
            i["ovl"] = np.max(ovl)
            occa[i["orb"]] = i["occ"]

    for i in range(nbf):
        Cocca.np[:,i] *= np.sqrt(occa[i])
        Coccb.np[:,i] *= np.sqrt(occb[i])


    Da     = Cocca.np @ Cocca.np.T
    Db     = Coccb.np @ Coccb.np.T

    jk = psi4.core.JK.build(wfn.basisset(),aux,"MEM_DF")
    glob_mem = psi4.core.get_memory()/8
    jk.set_memory(int(glob_mem*0.6))
    jk.initialize()
    jk.C_left_add(Cocca)
    jk.C_left_add(Coccb)

    Da_m = psi4.core.Matrix(nbf,nbf)
    Db_m = psi4.core.Matrix(nbf,nbf)

    diisa = DIIS_helper()
    diisb = DIIS_helper()

    gamma    =  psi4.core.get_local_option("PSIXAS","DAMP")
    diis_eps =  psi4.core.get_local_option("PSIXAS","DIIS_EPS")
    vshift   =  psi4.core.get_local_option("PSIXAS","VSHIFT")
    psi4.core.print_out("\nStarting SCF:\n"+13*"="+"\n\n{:>10} {:4.2f}\n{:>10} {:4.2f}\n{:>10} {:4.2f}\n\n".format("DAMP:",gamma,"DIIS_EPS:",diis_eps,"VSHIFT:",vshift))
 
    psi4.core.print_out("\nInitial orbital occupation pattern:\n\n")
    psi4.core.print_out("Index|Spin|Occ|Ovl|Freeze\n"+25*"-")
    for i in orbitals:
        psi4.core.print_out("\n{:^5}|{:^4}|{:^3}|{:^3}|{:^6}".format(i["orb"],i["spin"],i["occ"],'Yes' if i["DoOvl"] else 'No','Yes' if i["frz"] else 'No'))
    psi4.core.print_out("\n\n")




    psi4.core.print_out(("{:^3} {:^14} {:^14} {:^4} {:^4} | {:^"+str(len(orbitals)*5)+"}| {:^4} {:^5}\n").format("#IT", "Escf",
         "dEscf","na","nb",
         "OVL","MIX","Time"))
    psi4.core.print_out("="*80+"\n")

   
    myTimer = Timer()
    MIXMODE = "DAMP"
    for SCF_ITER in range(1, maxiter + 1):
        myTimer.addStart("SCF")

        myTimer.addStart("JK")
        jk.compute()
        myTimer.addEnd("JK")
        


        myTimer.addStart("buildFock")
        Da_m.np[:] = Da
        Db_m.np[:] = Db
        Vpot.set_D([Da_m,Db_m])
        myTimer.addStart("compV")
        Vpot.compute_V([Va,Vb])
        myTimer.addEnd("compV")

        Ja = np.asarray(jk.J()[0])
        Jb = np.asarray(jk.J()[1])
        Ka = np.asarray(jk.K()[0])
        Kb = np.asarray(jk.K()[1])

        if SCF_ITER>1 :
            FaOld = np.copy(Fa)
            FbOld = np.copy(Fb)

        Fa = H + (Ja + Jb) - Vpot.functional().x_alpha()*Ka + Va
        Fb = H + (Ja + Jb) - Vpot.functional().x_alpha()*Kb + Vb

        myTimer.addEnd("buildFock")
        """
        Fock matrix constructed: freeze orbitals if needed
        """
        myTimer.addStart("Freeze")        
        FMOa = Ca.T @ Fa @ Ca
        FMOb = Cb.T @ Fb @ Cb


        CaInv = np.linalg.inv(Ca)
        CbInv = np.linalg.inv(Cb)

        for i in orbitals:
            if i['frz'] == True:
                if i["spin"]=="b":
                    idx = i["orb"]
                    FMOb[idx,:idx]     = 0.0
                    FMOb[idx,(idx+1):] = 0.0
                    FMOb[:idx,idx]     = 0.0
                    FMOb[(idx+1):,idx] = 0.0
                elif i["spin"]=="a":
                    FMOa[idx,:idx]     = 0.0
                    FMOa[idx,(idx+1):] = 0.0
                    FMOa[:idx,idx]     = 0.0
                    FMOa[(idx+1):,idx] = 0.0
        """
        VSHIFT 
        """        
        idxs = [c for c,x in enumerate(occa) if (x ==0.0) and (c>=nalpha)]
        FMOa[idxs,idxs] += vshift
        idxs = [c for c,x in enumerate(occb) if (x ==0.0) and (c>=nbeta)]
        FMOb[idxs,idxs] += vshift

        Fa = CaInv.T @ FMOa @ CaInv
        Fb = CbInv.T @ FMOb @ CbInv

        myTimer.addEnd("Freeze")
        """
        END FREEZE
        """

        """
        DIIS/MIXING
        """
        myTimer.addStart("MIX")      
        
        diisa_e = Fa.dot(Da).dot(S) - S.dot(Da).dot(Fa)
        diisa_e = (A.T).dot(diisa_e).dot(A)
        diisa.add(Fa, diisa_e)

        diisb_e = Fb.dot(Db).dot(S) - S.dot(Db).dot(Fb)
        diisb_e = (A.T).dot(diisb_e).dot(A)
        diisb.add(Fb, diisb_e)

        if (MIXMODE == "DIIS") and (SCF_ITER>1):
            # Extrapolate alpha & beta Fock matrices separately
            Fa = diisa.extrapolate()
            Fb = diisb.extrapolate()
        elif (MIXMODE == "DAMP") and (SCF_ITER>1):
            # Use Damping to obtain the new Fock matrices
            Fa = (1-gamma) * np.copy(Fa) + (gamma) * FaOld
            Fb = (1-gamma) * np.copy(Fb) + (gamma) * FbOld
        
        myTimer.addEnd("MIX")    
        """
        END DIIS/MIXING
        """

        """
        CALC energy
        """
        myTimer.addStart("calcE")

        one_electron_E  = np.sum(Da * H)
        one_electron_E += np.sum(Db * H)
        coulomb_E       = np.sum(Da * (Ja+Jb))
        coulomb_E      += np.sum(Db * (Ja+Jb))

        alpha       = Vpot.functional().x_alpha()
        exchange_E  = 0.0
        exchange_E -= alpha * np.sum(Da * Ka)
        exchange_E -= alpha * np.sum(Db * Kb)

        XC_E = Vpot.quadrature_values()["FUNCTIONAL"]

        SCF_E = 0.0
        SCF_E += Enuc
        SCF_E += one_electron_E
        SCF_E += 0.5 * coulomb_E
        SCF_E += 0.5 * exchange_E
        SCF_E += XC_E
        myTimer.addEnd("calcE")
        
        # Diagonalize Fock matrix
        myTimer.addStart("Diag")
        Ca,epsa = diag_H(Fa, A)
        Cb,epsb = diag_H(Fb, A)
        myTimer.addEnd("Diag")

        """
        New orbitals obtained set occupation numbers
        """
        myTimer.addStart("SetOcc")

        Cocca.np[:]  = Ca
        Coccb.np[:]  = Cb


        occa[:] = 0.0
        occb[:] = 0.0

        occa[:nalpha] = 1.0  #standard aufbau principle occupation
        occb[:nbeta]  = 1.0


        for i in orbitals:
            if i["spin"]=="b":
                """
                Overlap
                """
                #calculate the Overlapp with all other orbitals
                ovl = np.abs(np.einsum('m,nj,mn->j',i["C"],Coccb,S))
                #User wants to switch the index if higher overlap is found
                if i["DoOvl"] ==True :
                    if i["orb"] != np.argmax(ovl):
                        i["orb"] = np.argmax(ovl)
                    i["ovl"] = np.max(ovl)
                else:
                    #just calculate the overlap to assess the character
                    i["ovl"] = ovl[i["orb"]]
                #Modify the occupation vector
                occb[i["orb"]] = i["occ"]

            elif i["spin"]=="a":
                """
                Check if this is still the largest overlap
                """
                ovl = np.abs(np.einsum('m,nj,mn->j',i["C"],Cocca,S))
                if i["DoOvl"] ==True :
                    if i["orb"] != np.argmax(ovl):
                        i["orb"] = np.argmax(ovl) # set index to the highest overlap
                    i["ovl"] = np.max(ovl)
                else:
                    i["ovl"] = ovl[i["orb"]]
                #Modify the occupation vector
                occa[i["orb"]] = i["occ"]
                

        for i in range(nbf):
            Cocca.np[:,i] *= np.sqrt(occa[i])
            Coccb.np[:,i] *= np.sqrt(occb[i])
        
        Da     = Cocca.np @ Cocca.np.T
        Db     = Coccb.np @ Coccb.np.T

        myTimer.addEnd("SetOcc")
        
        myTimer.addEnd("SCF")
        psi4.core.print_out(("{:3d} {:14.8f} {:14.8f} {:4.1f} {:4.1f} | "+"{:4.2f} "*len(orbitals)+"| {:^4} {:5.2f} \n").format(
            SCF_ITER,
            SCF_E,
            (SCF_E - Eold),
            np.sum(Da*S),
            np.sum(Db*S),
            *[x["ovl"] for x in orbitals],
            MIXMODE,
            myTimer.getTime("SCF") ))
        psi4.core.flush_outfile()
        myTimer.printAlltoFile("timers.ksex")
        
        if (abs(SCF_E - Eold) < diis_eps):
            MIXMODE = "DIIS"
        else:
            MIXMODE = "DAMP"  
        
        
        if (abs(SCF_E - Eold) < E_conv):
            if (vshift != 0.0):
                psi4.core.print_out("Converged but Vshift was on... removing Vshift..\n")
                vshift = 0.0
            else:
                break


        Eold = SCF_E   



        if SCF_ITER == maxiter:
            psi4.core.clean()
            raise Exception("Maximum number of SCF cycles exceeded.")

    psi4.core.print_out("\n\n{:>20} {:12.8f} [Ha] \n".format("FINAL EX SCF ENERGY:",SCF_E))

    
    gsE = psi4.core.scalar_variable('GS ENERGY')
    if gsE!=0.0:
        psi4.core.print_out("{:>20} {:12.8f} [Ha] \n".format("EXCITATION ENERGY:",SCF_E-gsE))
        psi4.core.print_out("{:>20} {:12.8f} [eV] \n\n".format("EXCITATION ENERGY:",(SCF_E-gsE)*27.211385))
    

    


    psi4.core.print_out("\nFinal orbital occupation pattern:\n\n")
    psi4.core.print_out("Index|Spin|Occ|Ovl|Freeze\n"+25*"-")
    for i in orbitals:
        if i["spin"] == "a":
            occ = occa[i["orb"]]
        else:
            occ = occb[i["orb"]]
        psi4.core.print_out("\n{:^5}|{:^4}|{:^3}|{:^3}|{:^6}".format(i["orb"],i["spin"],occ,'Yes' if i["DoOvl"] else 'No','Yes' if i["frz"] else 'No'))
    psi4.core.print_out("\n\n")




    OCCA = psi4.core.Vector("Alpha occupation", nbf)
    OCCB = psi4.core.Vector("Beta occupation", nbf)
    OCCA.np[:] = occa
    OCCB.np[:] = occb

    uhf.Ca().np[:] = Ca
    uhf.Cb().np[:] = Cb

    uhf.epsilon_a().np[:] = epsa
    uhf.epsilon_b().np[:] = epsb

    uhf.occupation_a().np[:] = occa
    uhf.occupation_b().np[:] = occb

    uhf.epsilon_a().print_out()
    uhf.epsilon_b().print_out()

    OCCA.print_out()
    OCCB.print_out()

    mw = psi4.core.MoldenWriter(uhf)
    mw.write(prefix+'_ex.molden',uhf.Ca(),uhf.Cb(),uhf.epsilon_a(),uhf.epsilon_b(),OCCA,OCCB,True)
    psi4.core.print_out("\n\n Moldenfile written\n")
    np.savez(prefix+'_exorbs',Ca=Ca,Cb=Cb,occa=occa,occb=occb,epsa=epsa,epsb=epsb,orbitals=orbitals)

    psi4.core.set_variable('CURRENT ENERGY', SCF_E)
    
    bas = wfn.basisset()

    with open("GENBAS", "w") as genbas:
        genbas.write(bas.genbas())
        
    maxl = bas.max_am()
    map = []
    lmap = [[0],
            [1,2,0],
            [0,4,1,3,2],
            [1,2,0,5,4,6,3],
            [0,4,1,7,6,3,8,5,2],
            [1,2,3,5,8,10,7,6,0,9,4],
            [11,4,9,7,10,3,12,5,8,0,6,2,1]]

    for i in range(mol.natom()):
        for l in range(maxl+1):
            for li in range(2*l+1):
                for j in range(bas.nshell()):
                    s = bas.shell(j)
                    if bas.shell_to_center(j) == i and s.am == l:
                        k = bas.shell_to_basis_function(j)
                        if l > 6:
                            m = l - li//2
                            k += 2*m + li%2
                        else:
                            k += lmap[l][li]
                        map.append(k)
                        
    assert(len(map) == mints.nbf())
    assert(sorted(map) == list(range(mints.nbf())))
        
    with open("OLDMOS", "w") as oldmos:
        for C in (Ca, Cb):
            for j0 in range(0,mints.nbf(),4):
                for i in range(mints.nbf()):
                    for j in range(j0,min(mints.nbf(),j0+4)):
                        oldmos.write("%30.20e" % (C[map[i]][j]));
                    oldmos.write('\n');
                
    open("JFSGUESS", "w").close()
